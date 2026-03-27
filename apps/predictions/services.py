"""
apps/predictions/services.py
══════════════════════════════
Orchestrates the full prediction flow:
  1. Fetch 28-day data
  2. Run ML pipeline
  3. Persist PredictionResult
  4. Notify patient
  5. Escalate to clinician / HCC / FHC if Severe or Extreme
"""

import logging
from datetime import date

from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db import transaction

from apps.health_checkin.services import DailySummaryService
from .ml_pipeline import run_inference, DISEASES
from .models import PredictionResult, PredictionSeverity

logger = logging.getLogger(__name__)
User = get_user_model()


class PredictionService:
    @staticmethod
    @transaction.atomic
    def run_for_summary(summary_id: str) -> PredictionResult:
        """
        Entry point called by Celery task after daily summary is assembled.
        """
        from apps.health_checkin.models import DailyCheckinSummary

        try:
            summary = DailyCheckinSummary.objects.select_related("user").get(pk=summary_id)
        except DailyCheckinSummary.DoesNotExist:
            raise ValueError(f"DailyCheckinSummary {summary_id} not found.")

        user = summary.user
        predict_date = summary.summary_date

        # Guard: don't re-run
        if summary.prediction_run:
            logger.info("Prediction already run for summary %s", summary_id)
            try:
                return PredictionResult.objects.get(user=user, prediction_date=predict_date)
            except PredictionResult.DoesNotExist:
                pass

        # Fetch pcos_label from onboarding profile if available
        pcos_label = 0
        try:
            from apps.onboarding.models import OnboardingProfile

            profile = OnboardingProfile.objects.get(user=user)
            # PCOS inference from mFG score (high androgen proxy)
            if (
                profile.bmi is not None
                and profile.bmi > 25
                and profile.cycle_regularity == "irregular"
            ):
                pcos_label = 1
        except Exception:
            pass

        # Load 28-day data
        daily_rows = DailySummaryService.get_28_day_data(user, reference_date=predict_date)

        # Run pipeline
        output = run_inference(daily_rows, pcos_label=pcos_label)

        # Persist
        result = PredictionService._persist(user, predict_date, output, summary)

        # Only notify if prediction actually has scores
        if result.status not in ("insufficient", "error") and result.infertility_score is not None:
            PredictionService._notify_patient(user, result)

        # Only escalate if severe/extreme
        if result.requires_escalation():
            PredictionService._escalate(user, result)

        # Mark summary as done
        summary.prediction_run = True
        summary.prediction_run_at = timezone.now()
        summary.save(update_fields=["prediction_run", "prediction_run_at"])

        logger.info(
            "Prediction complete for %s on %s | status=%s",
            user.email,
            predict_date,
            result.status,
        )
        return result

    @staticmethod
    def _persist(user: User, predict_date: date, output, summary) -> PredictionResult:
        """Upsert the PredictionResult record."""

        def dr(disease_name):
            obj = getattr(output, disease_name.lower(), None)
            if obj is None:
                return {
                    f"{disease_name.lower()}_score": None,
                    f"{disease_name.lower()}_flag": None,
                    f"{disease_name.lower()}_severity": "",
                    f"{disease_name.lower()}_risk_prob": None,
                }
            return {
                f"{disease_name.lower()}_score": obj.score,
                f"{disease_name.lower()}_flag": obj.flag,
                f"{disease_name.lower()}_severity": obj.severity,
                f"{disease_name.lower()}_risk_prob": obj.risk_prob,
            }

        fields = {}
        for disease in DISEASES:
            fields.update(dr(disease))

        result, _ = PredictionResult.objects.update_or_create(
            user=user,
            prediction_date=predict_date,
            defaults={
                "daily_summary": summary,
                "model_version": output.model_version,
                "symptom_burden_score": output.symptom_burden_score,
                "feature_vector": output.feature_vector,
                "raw_daily_data": output.raw_daily_data,
                "days_of_data": output.days_of_data,
                "data_completeness_pct": output.data_completeness_pct,
                "status": output.status,
                "error_message": output.error_message,
                **fields,
            },
        )
        return result

    @staticmethod
    def _notify_patient(user: User, result: PredictionResult):
        """Send in-app notification with prediction summary."""
        try:
            from apps.notifications.models import Notification
            from apps.notifications.services import NotificationService

            worst_disease, worst_severity = result.get_highest_severity_disease()

            severity_emoji = {
                "Minimal": "✅",
                "Mild": "🟡",
                "Moderate": "🟠",
                "Severe": "🔴",
                "Extreme": "🚨",
            }.get(worst_severity, "ℹ️")

            title = f"{severity_emoji} Your health risk scores are ready"
            body = (
                f"Based on {result.days_of_data} days of check-ins, "
                f"your highest risk is {worst_disease} — {worst_severity}. "
                "Tap to view your full report."
            )

            NotificationService.send(
                recipient=user,
                notification_type=Notification.NotificationType.RISK_UPDATE,
                title=title,
                body=body,
                priority=(
                    Notification.Priority.HIGH
                    if worst_severity in ("Severe", "Extreme")
                    else Notification.Priority.MEDIUM
                ),
                data={
                    "prediction_id": str(result.id),
                    "prediction_date": str(result.prediction_date),
                    "worst_disease": worst_disease,
                    "worst_severity": worst_severity,
                    "action": "open_prediction_report",
                },
            )

            result.patient_notified = True
            result.save(update_fields=["patient_notified"])

        except Exception as e:
            logger.error("Failed to notify patient %s: %s", user.email, e)

    @staticmethod
    def _escalate(user: User, result: PredictionResult):
        """
        Escalate to PHC/FMC based on severity.
        - Mild/Moderate → PHCPatientRecord at patient's registered PHC
        - Severe/Very Severe → PatientCase at PHC's linked FMC
        """
        try:
            from apps.centers.signals import notify_center_of_critical_risk
            from apps.centers.models import RiskSeverity

            # Map prediction severity to centers.RiskSeverity
            severity_map = {
                "Minimal": None,  # Don't escalate Minimal
                "Mild": RiskSeverity.MILD,
                "Moderate": RiskSeverity.MODERATE,
                "Severe": RiskSeverity.SEVERE,
                "Extreme": RiskSeverity.VERY_SEVERE,
            }

            diseases_to_escalate = {
                "pcos": (result.infertility_severity, result.infertility_score),
                "maternal": (result.dysmenorrhea_severity, result.dysmenorrhea_score),
                "cardiovascular": (result.cvd_severity, result.cvd_score),
            }

            for condition, (severity_str, score) in diseases_to_escalate.items():
                mapped = severity_map.get(severity_str)
                if mapped and score is not None:
                    logger.info(
                        "Escalating %s: patient=%s condition=%s severity=%s score=%d",
                        user.email,
                        condition,
                        mapped,
                        int((score or 0) * 100),
                    )
                    notify_center_of_critical_risk(
                        patient=user,
                        condition=condition,
                        severity=mapped,
                        score=int((score or 0) * 100),
                    )

        except Exception as e:
            logger.error("Escalation failed for %s: %s", user.email, e)


class ClinicalRulesEngine:
    """
    Evaluates clinical rules based on Rotterdam Criteria and clinical knowledge.

    Returns:
        - triggered_rules: List of clinical rule names that fired
        - total_boost: Total score boost to apply
        - rule_details: Detailed breakdown of each rule
    """

    @staticmethod
    def evaluate_all(
        model_predictions: dict, per_disease_scores: dict, weights_config: dict
    ) -> tuple:
        """
        Evaluate all clinical rules and return boost amounts.

        Args:
            model_predictions: Dict of model predictions {model: {disease: pred}}
            per_disease_scores: Dict of calculated disease scores
            weights_config: Dict of disease weights

        Returns:
            (triggered_rules, total_boost, rule_details)
        """
        triggered_rules = []
        total_boost = 0.0
        rule_details = {}

        # Get PCOS weights for boost values
        pcos_weights = weights_config.get("PCOS", {})
        rotterdam_2_boost = pcos_weights.get("rotterdam_2_criteria_boost", 0.05)
        rotterdam_3_boost = pcos_weights.get("rotterdam_3_criteria_boost", 0.10)
        metabolic_repro_boost = pcos_weights.get("metabolic_reproductive_boost", 0.05)
        mood_rppg_boost = pcos_weights.get("mood_rppg_stress_boost", 0.03)

        # Rule 1: Rotterdam Criteria Evaluation
        rotterdam_result = ClinicalRulesEngine._evaluate_rotterdam(model_predictions)
        if rotterdam_result["criteria_met"] == 3:
            triggered_rules.append("rotterdam_3_criteria_met")
            total_boost += rotterdam_3_boost
            rule_details["rotterdam_3_criteria_met"] = {
                "boost": rotterdam_3_boost,
                "criteria": rotterdam_result["criteria"],
                "description": "All 3 Rotterdam criteria met - full PCOS diagnosis likely",
            }
        elif rotterdam_result["criteria_met"] >= 2:
            triggered_rules.append("rotterdam_2_criteria_met")
            total_boost += rotterdam_2_boost
            rule_details["rotterdam_2_criteria_met"] = {
                "boost": rotterdam_2_boost,
                "criteria": rotterdam_result["criteria"],
                "description": "2 Rotterdam criteria met - PCOS diagnosis probable",
            }

        # Rule 2: Metabolic + Reproductive Clustering
        metabolic_result = ClinicalRulesEngine._evaluate_metabolic_cluster(model_predictions)
        if metabolic_result["triggered"]:
            triggered_rules.append("metabolic_reproductive_cluster")
            total_boost += metabolic_repro_boost
            rule_details["metabolic_reproductive_cluster"] = {
                "boost": metabolic_repro_boost,
                "metabolic_score": metabolic_result["metabolic_score"],
                "reproductive_score": metabolic_result["reproductive_score"],
                "description": "Metabolic stress + reproductive dysfunction clustering detected",
            }

        # Rule 3: Mood + rPPG Stress Stack
        stress_result = ClinicalRulesEngine._evaluate_stress_stack(model_predictions)
        if stress_result["triggered"]:
            triggered_rules.append("mood_rppg_stress_stack")
            total_boost += mood_rppg_boost
            rule_details["mood_rppg_stress_stack"] = {
                "boost": mood_rppg_boost,
                "mood_score": stress_result["mood_score"],
                "rppg_stress_score": stress_result["rppg_stress_score"],
                "description": "Mood + rPPG stress both moderate+ - synergistic effect",
            }

        # Rule 4: Severe Amplification (any model at Severe+)
        severe_result = ClinicalRulesEngine._evaluate_severe_amplification(model_predictions)
        if severe_result["triggered"]:
            triggered_rules.append("severe_amplification")
            # Additional 5% for severe cases
            severe_boost = 0.05
            total_boost += severe_boost
            rule_details["severe_amplification"] = {
                "boost": severe_boost,
                "severe_diseases": severe_result["severe_diseases"],
                "description": "Severe/Extreme risk detected in multiple models",
            }

        # Cap total boost at 0.25 (25%)
        total_boost = min(total_boost, 0.25)

        return triggered_rules, total_boost, rule_details

    @staticmethod
    def _evaluate_rotterdam(model_predictions: dict) -> dict:
        """
        Evaluate Rotterdam Criteria for PCOS diagnosis.

        Criterion 1: Oligo/anovulation (irregular cycles)
        Criterion 2: Hyperandrogenism (signs in symptom model)
        Criterion 3: Polycystic ovaries (requires ultrasound - not in our models)
        """
        criteria_met = 0
        criteria = []

        symptom = model_predictions.get("symptom", {})
        menstrual = model_predictions.get("menstrual", {})

        # Criterion 1: Ovulatory Dysfunction
        # High Dysmenorrhea, PMDD, or Endometrial scores indicate cycle issues
        dysmenorrhea = menstrual.get("Dysmenorrhea", {}).get("risk_score", 0)
        pmdd_menstrual = menstrual.get("PMDD", {}).get("risk_score", 0)
        if dysmenorrhea > 0.4 or pmdd_menstrual > 0.4:
            criteria_met += 1
            criteria.append("oligomenorrhea_detected")

        # Criterion 2: Hyperandrogenism
        # PMDD in symptom model indicates hormonal issues
        pmdd_symptom = symptom.get("PMDD", {}).get("risk_score", 0)
        if pmdd_symptom > 0.4:
            criteria_met += 1
            criteria.append("hyperandrogenism_signs")

        # Criterion 3: Polycystic ovaries - not directly measured
        # Could infer from combination of menstrual + rPPG

        return {
            "criteria_met": criteria_met,
            "criteria": criteria,
            "has_oligomenorrhea": "oligomenorrhea_detected" in criteria,
            "has_hyperandrogenism": "hyperandrogenism_signs" in criteria,
        }

    @staticmethod
    def _evaluate_metabolic_cluster(model_predictions: dict) -> dict:
        """
        Evaluate metabolic + reproductive dysfunction clustering.
        Common in PCOS-Metabolic Syndrome overlap.
        """
        menstrual = model_predictions.get("menstrual", {})
        rppg = model_predictions.get("rppg", {})

        # Metabolic stress from rPPG
        metabolic = rppg.get("Metabolic", {}).get("risk_score", 0)
        stress = rppg.get("Stress", {}).get("risk_score", 0)

        # Reproductive dysfunction from menstrual
        infertility = menstrual.get("Infertility", {}).get("risk_score", 0)
        dysmenorrhea = menstrual.get("Dysmenorrhea", {}).get("risk_score", 0)

        metabolic_score = max(metabolic, stress)
        reproductive_score = max(infertility, dysmenorrhea)

        triggered = metabolic_score > 0.5 and reproductive_score > 0.4

        return {
            "triggered": triggered,
            "metabolic_score": metabolic_score,
            "reproductive_score": reproductive_score,
        }

    @staticmethod
    def _evaluate_stress_stack(model_predictions: dict) -> dict:
        """
        Evaluate mood + rPPG stress combination.
        Stress-hormone cycle can amplify both mental and physical risk.
        """
        mood = model_predictions.get("mood", {})
        rppg = model_predictions.get("rppg", {})

        # Mood stress (anxiety + chronic stress)
        anxiety = mood.get("Anxiety", {}).get("risk_score", 0)
        chronic_stress = mood.get("ChronicStress", {}).get("risk_score", 0)

        # rPPG stress
        stress = rppg.get("Stress", {}).get("risk_score", 0)

        mood_score = max(anxiety, chronic_stress)
        rppg_stress_score = stress

        triggered = mood_score > 0.4 and rppg_stress_score > 0.4

        return {
            "triggered": triggered,
            "mood_score": mood_score,
            "rppg_stress_score": rppg_stress_score,
        }

    @staticmethod
    def _evaluate_severe_amplification(model_predictions: dict) -> dict:
        """
        Check if any model shows Severe or Extreme severity.
        """
        severe_diseases = []

        for model_name, predictions in model_predictions.items():
            if isinstance(predictions, dict):
                for disease, pred in predictions.items():
                    if isinstance(pred, dict):
                        severity = pred.get("severity", "")
                        if severity in ("Severe", "Extreme"):
                            severe_diseases.append(
                                {
                                    "disease": disease,
                                    "model": model_name,
                                    "severity": severity,
                                    "score": pred.get("risk_score", 0),
                                }
                            )

        # Trigger if 2+ models have severe cases
        triggered = len(severe_diseases) >= 2

        return {
            "triggered": triggered,
            "severe_diseases": severe_diseases,
        }


class ComprehensiveInferenceService:
    """
    Runs all available ML models and creates a unified comprehensive prediction.

    This is the single source of truth for:
    - Patient Dashboard PCOS Risk Score
    - PCOSRiskScore detailed breakdown
    - Per-model escalation triggers
    """

    # Map model disease names to condition types for escalation
    DISEASE_TO_CONDITION = {
        # Symptom/Menstrual
        "Infertility": "pcos",
        "Dysmenorrhea": "maternal",
        "PMDD": "maternal",
        "Endometrial": "maternal",
        "T2D": "cardiovascular",
        "CVD": "cardiovascular",
        # rPPG
        "Stress": "cardiovascular",
        "Metabolic": "cardiovascular",
        "HeartFailure": "cardiovascular",
        # Mood
        "Anxiety": "cardiovascular",
        "Depression": "cardiovascular",
        "ChronicStress": "cardiovascular",
        "Stroke": "cardiovascular",
    }

    # Severity that triggers escalation
    ESCALATE_SEVERITIES = {"Moderate", "Severe", "Extreme"}

    @staticmethod
    def run_full_inference(user: User) -> "ComprehensivePredictionResult":
        """
        Run all available models and create comprehensive prediction.
        Triggered by: check-in completion, rPPG session, mood tracking, manual request.
        """
        from apps.predictions.models import ComprehensivePredictionResult
        from apps.centers.signals import notify_center_of_critical_risk
        from apps.centers.models import RiskSeverity
        from apps.ml_proxy.proxy import nodejs_post

        all_predictions = {}
        data_layers = []

        # 1. SYMPTOM MODEL (Django) - from check-in data
        symptom_preds = ComprehensiveInferenceService._run_symptom_model(user)
        if symptom_preds:
            all_predictions["symptom"] = symptom_preds
            data_layers.append("symptom")

        # 2. MENSTRUAL MODEL (Node.js)
        menstrual_preds = ComprehensiveInferenceService._run_menstrual_model(user)
        if menstrual_preds:
            all_predictions["menstrual"] = menstrual_preds
            data_layers.append("menstrual")

        # 3. rPPG MODEL (Node.js)
        rppg_preds = ComprehensiveInferenceService._run_rppg_model(user)
        if rppg_preds:
            all_predictions["rppg"] = rppg_preds
            data_layers.append("rppg")

        # 4. MOOD MODEL (Node.js)
        mood_preds = ComprehensiveInferenceService._run_mood_model(user)
        if mood_preds:
            all_predictions["mood"] = mood_preds
            data_layers.append("mood")

        if not all_predictions:
            logger.warning("No predictions available for user %s", user.email)
            return None

        # Calculate weighted ensemble scores
        ensemble_result = ComprehensiveInferenceService._calculate_weighted_ensemble(
            all_predictions, user
        )

        final_score = ensemble_result["overall_risk_score"]
        pcos_specific_score = ensemble_result["pcos_specific_score"]
        per_disease_scores = ensemble_result["per_disease_scores"]
        clinical_rules_triggered = ensemble_result["clinical_rules_triggered"]
        calculation_breakdown = ensemble_result["calculation_breakdown"]
        weights_used = ensemble_result["weights_used"]

        risk_tier = ComprehensivePredictionResult.calculate_risk_tier(final_score)

        # Find highest risk disease for tracking
        highest_disease = (
            max(per_disease_scores, key=per_disease_scores.get) if per_disease_scores else ""
        )
        highest_score = per_disease_scores.get(highest_disease, 0) if per_disease_scores else 0

        # Determine which model contributed most to highest disease
        highest_model = ""
        if highest_disease:
            for model_name, preds in all_predictions.items():
                if (
                    highest_disease in preds
                    and preds[highest_disease].get("risk_score", 0) == highest_score
                ):
                    highest_model = model_name
                    break

        # Compute severity flags
        severity_flags = ComprehensiveInferenceService._compute_severity_flags(all_predictions)

        # Calculate data completeness (each layer = 25%)
        data_completeness = len(data_layers) * 25

        # Create comprehensive result
        result = ComprehensivePredictionResult.objects.create(
            user=user,
            final_risk_score=round(final_score, 4),
            risk_tier=risk_tier,
            pcos_specific_score=round(pcos_specific_score, 4) if pcos_specific_score else None,
            per_disease_scores=per_disease_scores,
            weights_used=weights_used,
            clinical_rules_triggered=clinical_rules_triggered,
            calculation_breakdown=calculation_breakdown,
            symptom_predictions=all_predictions.get("symptom", {}),
            menstrual_predictions=all_predictions.get("menstrual", {}),
            rppg_predictions=all_predictions.get("rppg", {}),
            mood_predictions=all_predictions.get("mood", {}),
            data_layers_used=data_layers,
            data_completeness_pct=data_completeness,
            severity_flags=severity_flags,
            highest_risk_disease=highest_disease,
            highest_risk_model=highest_model,
        )

        # Trigger per-model escalations
        ComprehensiveInferenceService._trigger_per_model_escalations(
            user=user,
            all_predictions=all_predictions,
        )

        logger.info(
            "Comprehensive prediction for %s: overall=%.4f pcos=%.4f tier=%s layers=%s rules=%s",
            user.email,
            final_score,
            pcos_specific_score or 0,
            risk_tier,
            data_layers,
            clinical_rules_triggered,
        )

        return result

    @staticmethod
    def _calculate_weighted_ensemble(model_predictions: dict, user: User) -> dict:
        """
        Calculate weighted ensemble scores for all diseases.

        Uses database-configured weights per disease, with clinical rule boosts.
        """
        from apps.predictions.models import EnsembleWeightConfig

        # 1. Get weights from database (with defaults fallback)
        weights_config = ComprehensiveInferenceService._get_weights_from_db()

        # 2. Calculate data quality adjustment (more data = more reliable)
        quality_scores = ComprehensiveInferenceService._calculate_data_quality(model_predictions)

        # 3. Adjust weights based on data quality
        adjusted_weights = ComprehensiveInferenceService._adjust_weights_for_quality(
            weights_config, quality_scores
        )

        # 4. Calculate base scores per disease using weighted ensemble
        per_disease_scores = {}
        base_scores = {}

        # Normalize disease names (some models use _Mood suffix)
        disease_normalization = {
            "T2D_Mood": "T2D",
            "MetSyn_Mood": "Metabolic",
            "CVD_Mood": "CVD",
            "Stroke_Mood": "Stroke",
            "Infertility_Mood": "Infertility",
        }

        # Get all unique diseases across all models
        all_diseases = set()
        for model_name, predictions in model_predictions.items():
            for disease in predictions.keys():
                normalized = disease_normalization.get(disease, disease)
                all_diseases.add(normalized)

        # Calculate score for each disease
        for disease in all_diseases:
            disease_scores = {}

            for model_name, predictions in model_predictions.items():
                # Try original name and normalized name
                score = None
                for dn in [disease, disease + "_Mood"]:
                    if dn in predictions:
                        score = float(predictions[dn].get("risk_score", 0))
                        break

                if score is not None:
                    disease_scores[model_name] = score

            # Apply weighted average
            if disease_scores and disease in adjusted_weights:
                disease_weights = adjusted_weights[disease]

                weighted_sum = 0.0
                weight_total = 0.0

                for model_name, score in disease_scores.items():
                    if model_name in disease_weights:
                        model_weight = disease_weights[model_name]
                        weighted_sum += score * model_weight
                        weight_total += model_weight

                if weight_total > 0:
                    base_score = weighted_sum / weight_total
                else:
                    base_score = sum(disease_scores.values()) / len(disease_scores)

                per_disease_scores[disease] = round(base_score, 4)
                base_scores[disease] = round(base_score, 4)

        # 5. Calculate PCOS-specific score with clinical rules
        pcos_score = per_disease_scores.get("PCOS", 0)

        # Apply clinical rules
        triggered_rules, total_boost, rule_details = ClinicalRulesEngine.evaluate_all(
            model_predictions, per_disease_scores, weights_config
        )

        # Apply boost to PCOS score
        pcos_score_with_boost = min(pcos_score + total_boost, 1.0)

        # 6. Calculate overall risk (weighted average of all disease scores)
        if per_disease_scores:
            overall_risk = sum(per_disease_scores.values()) / len(per_disease_scores)
        else:
            overall_risk = 0.0

        # 7. Build calculation breakdown
        calculation_breakdown = {
            "base_scores": base_scores,
            "boost_applied": total_boost,
            "clinical_rules_details": rule_details,
            "data_quality": quality_scores,
            "weight_adjustments": {
                disease: {
                    model: adjusted_weights[disease].get(model, 0)
                    for model in ["symptom", "menstrual", "rppg", "mood"]
                }
                for disease in adjusted_weights
            },
        }

        # Clean up weights_used for storage (simplified format)
        weights_used = {
            disease: disease_weights.get_weight_dict()
            for disease, disease_weights in adjusted_weights.items()
        }

        return {
            "overall_risk_score": round(overall_risk, 4),
            "pcos_specific_score": round(pcos_score_with_boost, 4),
            "per_disease_scores": per_disease_scores,
            "clinical_rules_triggered": triggered_rules,
            "calculation_breakdown": calculation_breakdown,
            "weights_used": weights_used,
        }

    @staticmethod
    def _get_weights_from_db() -> dict:
        """Get weights from database, falling back to defaults."""
        from apps.predictions.models import EnsembleWeightConfig

        default_weights = EnsembleWeightConfig.get_default_weights()

        try:
            configs = EnsembleWeightConfig.objects.filter(is_active=True)

            weights_dict = {}
            for config in configs:
                disease = config.disease_name
                weights_dict[disease] = {
                    "symptom": config.symptom_weight,
                    "menstrual": config.menstrual_weight,
                    "rppg": config.rppg_weight,
                    "mood": config.mood_weight,
                    "rotterdam_2_criteria_boost": config.rotterdam_2_criteria_boost,
                    "rotterdam_3_criteria_boost": config.rotterdam_3_criteria_boost,
                    "metabolic_reproductive_boost": config.metabolic_reproductive_boost,
                    "mood_rppg_stress_boost": config.mood_rppg_stress_boost,
                }

            # Merge with defaults for diseases not in DB
            for disease, default in default_weights.items():
                if disease not in weights_dict:
                    weights_dict[disease] = default

            return weights_dict

        except Exception as e:
            logger.warning("Error fetching weights from DB, using defaults: %s", e)
            return {
                disease: {
                    **weights,
                    "rotterdam_2_criteria_boost": 0.05,
                    "rotterdam_3_criteria_boost": 0.10,
                    "metabolic_reproductive_boost": 0.05,
                    "mood_rppg_stress_boost": 0.03,
                }
                for disease, weights in default_weights.items()
            }

    @staticmethod
    def _calculate_data_quality(model_predictions: dict) -> dict:
        """
        Calculate data quality score for each model.
        More data = higher quality = more reliable predictions.
        """
        quality = {}

        # Symptom model: based on days of check-in data
        symptom = model_predictions.get("symptom", {})
        quality["symptom"] = 1.0 if symptom else 0.0

        # Menstrual model: based on cycles logged
        menstrual = model_predictions.get("menstrual", {})
        quality["menstrual"] = 1.0 if menstrual else 0.0

        # rPPG model: based on sessions
        rppg = model_predictions.get("rppg", {})
        quality["rppg"] = 1.0 if rppg else 0.0

        # Mood model: based on weekly tools completion
        mood = model_predictions.get("mood", {})
        quality["mood"] = 1.0 if mood else 0.0

        return quality

    @staticmethod
    def _adjust_weights_for_quality(weights_config: dict, quality_scores: dict) -> dict:
        """
        Adjust weights based on data quality.
        Models with more data get higher effective weight.
        """
        adjusted = {}

        # Calculate total quality
        total_quality = sum(quality_scores.values())
        if total_quality == 0:
            return weights_config

        for disease, weights in weights_config.items():
            adjusted_weights = {}
            total_adjusted = 0.0

            for model in ["symptom", "menstrual", "rppg", "mood"]:
                base_weight = weights.get(model, 0.25)
                quality = quality_scores.get(model, 0)

                # Adjust weight: quality * base_weight
                adjusted_weight = quality * base_weight
                adjusted_weights[model] = adjusted_weight
                total_adjusted += adjusted_weight

            # Normalize to sum to 1.0
            if total_adjusted > 0:
                for model in adjusted_weights:
                    adjusted_weights[model] /= total_adjusted

            # Store as EnsembleWeightConfig-like object for get_weight_dict()
            class WeightWrapper:
                def __init__(self, weights):
                    self._weights = weights

                def get_weight_dict(self):
                    return self._weights

            adjusted[disease] = WeightWrapper(adjusted_weights)

        return adjusted

    @staticmethod
    def _run_symptom_model(user: User) -> dict:
        """Run symptom intensity model from Django."""
        try:
            daily_rows = DailySummaryService.get_28_day_data(user)
            output = run_inference(daily_rows)

            if output.status in ("success", "partial"):
                return {
                    "Infertility": {
                        "risk_score": output.infertility.score,
                        "severity": output.infertility.severity,
                    },
                    "Dysmenorrhea": {
                        "risk_score": output.dysmenorrhea.score,
                        "severity": output.dysmenorrhea.severity,
                    },
                    "PMDD": {"risk_score": output.pmdd.score, "severity": output.pmdd.severity},
                    "T2D": {"risk_score": output.t2d.score, "severity": output.t2d.severity},
                    "CVD": {"risk_score": output.cvd.score, "severity": output.cvd.severity},
                    "Endometrial": {
                        "risk_score": output.endometrial.score,
                        "severity": output.endometrial.severity,
                    },
                }
        except Exception as e:
            logger.warning("Symptom model failed for %s: %s", user.email, e)
        return {}

    @staticmethod
    def _run_menstrual_model(user: User) -> dict:
        """Run menstrual model from Node.js."""
        try:
            from apps.ml_proxy.proxy import nodejs_post

            menstrual_data, _ = nodejs_post(user.id, "/api/v1/menstrual/predict")
            if menstrual_data and menstrual_data.get("success"):
                preds = menstrual_data.get("data", {}).get("predictions", {})
                return {
                    disease: {
                        "risk_score": pred.get("risk_score", 0),
                        "severity": pred.get("severity", "Minimal"),
                    }
                    for disease, pred in preds.items()
                }
        except Exception as e:
            logger.warning("Menstrual model failed for %s: %s", user.email, e)
        return {}

    @staticmethod
    def _run_rppg_model(user: User) -> dict:
        """Run rPPG/HRV model from Node.js."""
        try:
            from apps.ml_proxy.proxy import nodejs_post

            predictions = {}

            # Metabolic/Cardio predictions
            metabolic_data, _ = nodejs_post(user.id, "/api/v1/rppg/predict/metabolic-cardio")
            if metabolic_data and metabolic_data.get("success"):
                preds = metabolic_data.get("data", {}).get("predictions", {})
                for disease, pred in preds.items():
                    predictions[disease] = {
                        "risk_score": pred.get("risk_score", 0),
                        "severity": pred.get("severity", "Minimal"),
                    }

            # Stress/Reproductive predictions
            reproductive_data, _ = nodejs_post(user.id, "/api/v1/rppg/predict/stress-reproductive")
            if reproductive_data and reproductive_data.get("success"):
                preds = reproductive_data.get("data", {}).get("predictions", {})
                for disease, pred in preds.items():
                    predictions[disease] = {
                        "risk_score": pred.get("risk_score", 0),
                        "severity": pred.get("severity", "Minimal"),
                    }

            return predictions
        except Exception as e:
            logger.warning("rPPG model failed for %s: %s", user.email, e)
        return {}

    @staticmethod
    def _run_mood_model(user: User) -> dict:
        """Run mood model from Node.js."""
        try:
            from apps.ml_proxy.proxy import nodejs_post

            predictions = {}
            mood_groups = {
                "mental_health": ["Anxiety", "Depression", "PMDD", "ChronicStress"],
                "metabolic": ["T2D_Mood", "MetSyn_Mood"],
                "cardio_neuro": ["CVD_Mood", "Stroke_Mood"],
                "reproductive": ["Infertility_Mood"],
            }

            for group, diseases in mood_groups.items():
                try:
                    mood_data, _ = nodejs_post(user.id, f"/api/v1/mood/predict/{group}")
                    if mood_data and mood_data.get("success"):
                        preds = mood_data.get("data", {}).get("predictions", {})
                        for disease in diseases:
                            if disease in preds:
                                pred = preds[disease]
                                predictions[disease] = {
                                    "risk_score": pred.get("risk_score", 0),
                                    "severity": pred.get("severity", "Minimal"),
                                }
                except Exception:
                    pass

            return predictions
        except Exception as e:
            logger.warning("Mood model failed for %s: %s", user.email, e)
        return {}

    @staticmethod
    def _compute_severity_flags(all_predictions: dict) -> dict:
        """
        Compute clinical severity flags based on Rotterdam Criteria.

        Returns dict with boolean flags for clinical interpretation.
        """
        flags = {
            "ovulatory_dysfunction": False,
            "hyperandrogenism": False,
            "metabolic_stress": False,
            "pcom_suspected": False,
        }

        # Check Criterion 1: Ovulatory Dysfunction
        # Look for cycle-related issues in menstrual predictions
        menstrual = all_predictions.get("menstrual", {})
        if menstrual:
            # High Dysmenorrhea or cycle-related issues
            dysmenorrhea_score = menstrual.get("Dysmenorrhea", {}).get("risk_score", 0)
            if dysmenorrhea_score and dysmenorrhea_score > 0.4:
                flags["ovulatory_dysfunction"] = True

        # Check Criterion 2: Hyperandrogenism
        # Look for mFG or acne-related scores in symptom predictions
        symptom = all_predictions.get("symptom", {})
        if symptom:
            pmdd_score = symptom.get("PMDD", {}).get("risk_score", 0)
            if pmdd_score and pmdd_score > 0.4:
                flags["hyperandrogenism"] = True

        # Check metabolic stress from rPPG
        rppg = all_predictions.get("rppg", {})
        if rppg:
            stress_score = rppg.get("Stress", {}).get("risk_score", 0)
            metabolic_score = rppg.get("Metabolic", {}).get("risk_score", 0)
            if (stress_score and stress_score > 0.5) or (metabolic_score and metabolic_score > 0.5):
                flags["metabolic_stress"] = True

        # PCOM suspected: combination of indicators
        criterion_count = sum(
            [
                flags["ovulatory_dysfunction"],
                flags["hyperandrogenism"],
                flags["metabolic_stress"],
            ]
        )
        if criterion_count >= 2:
            flags["pcom_suspected"] = True

        return flags

    @staticmethod
    def _trigger_per_model_escalations(user: User, all_predictions: dict):
        """
        Trigger escalation for each model independently.
        If any prediction is Moderate+, escalate to PHC.
        If any is Severe/Extreme, escalate to FMC.
        """
        from apps.centers.signals import notify_center_of_critical_risk
        from apps.centers.models import RiskSeverity

        severity_to_risk = {
            "Moderate": RiskSeverity.MODERATE,
            "Severe": RiskSeverity.SEVERE,
            "Extreme": RiskSeverity.VERY_SEVERE,
        }

        escalated_conditions = set()

        for model_name, predictions in all_predictions.items():
            for disease, pred in predictions.items():
                if not isinstance(pred, dict):
                    continue

                severity = pred.get("severity", "Minimal")
                score = pred.get("risk_score", 0)

                if severity in severity_to_risk and score:
                    condition = ComprehensiveInferenceService.DISEASE_TO_CONDITION.get(
                        disease, "pcos"
                    )

                    # Avoid duplicate escalations for same condition
                    escalation_key = f"{model_name}_{condition}"
                    if escalation_key in escalated_conditions:
                        continue
                    escalated_conditions.add(escalation_key)

                    risk_severity = severity_to_risk[severity]
                    score_int = int(score * 100)

                    logger.info(
                        "Per-model escalation: user=%s model=%s disease=%s severity=%s score=%d",
                        user.email,
                        model_name,
                        disease,
                        risk_severity,
                        score_int,
                    )

                    try:
                        notify_center_of_critical_risk(
                            patient=user,
                            condition=condition,
                            severity=risk_severity,
                            score=score_int,
                        )
                    except Exception as e:
                        logger.error("Per-model escalation failed: %s", e)

    @staticmethod
    def get_latest_result(user: User) -> "ComprehensivePredictionResult | None":
        """Get the most recent comprehensive prediction for a user."""
        from apps.predictions.models import ComprehensivePredictionResult

        return ComprehensivePredictionResult.objects.filter(user=user).first()

    @staticmethod
    def trigger_from_checkin(user: User):
        """Trigger comprehensive inference after check-in completion."""
        result = ComprehensiveInferenceService.run_full_inference(user)
        return result

    @staticmethod
    def trigger_from_rppg_session(user: User):
        """Trigger comprehensive inference after rPPG session captured."""
        result = ComprehensiveInferenceService.run_full_inference(user)
        return result

    @staticmethod
    def trigger_from_mood_tracking(user: User):
        """Trigger comprehensive inference after mood tracking completion."""
        result = ComprehensiveInferenceService.run_full_inference(user)
        return result

    @staticmethod
    def trigger_from_menstrual_tracking(user: User):
        """Trigger comprehensive inference after menstrual tracking."""
        result = ComprehensiveInferenceService.run_full_inference(user)
        return result

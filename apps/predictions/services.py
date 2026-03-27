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

        # Calculate final score (MAX across all models)
        all_scores = []
        highest_disease = ""
        highest_model = ""
        highest_score = 0

        for model_name, predictions in all_predictions.items():
            for disease, pred in predictions.items():
                if isinstance(pred, dict) and pred.get("risk_score"):
                    score = float(pred["risk_score"])
                    all_scores.append(score)
                    if score > highest_score:
                        highest_score = score
                        highest_disease = disease
                        highest_model = model_name

        final_score = max(all_scores) if all_scores else 0.0
        risk_tier = ComprehensivePredictionResult.calculate_risk_tier(final_score)

        # Compute severity flags
        severity_flags = ComprehensiveInferenceService._compute_severity_flags(all_predictions)

        # Calculate data completeness (each layer = 25%)
        data_completeness = len(data_layers) * 25

        # Create comprehensive result
        result = ComprehensivePredictionResult.objects.create(
            user=user,
            final_risk_score=round(final_score, 4),
            risk_tier=risk_tier,
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
            "Comprehensive prediction for %s: score=%.4f tier=%s layers=%s",
            user.email,
            final_score,
            risk_tier,
            data_layers,
        )

        return result

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

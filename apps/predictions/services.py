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

        user          = summary.user
        predict_date  = summary.summary_date

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
            if profile.bmi is not None and profile.bmi > 25 and profile.cycle_regularity == "irregular":
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
        summary.prediction_run    = True
        summary.prediction_run_at = timezone.now()
        summary.save(update_fields=["prediction_run", "prediction_run_at"])

        logger.info(
            "Prediction complete for %s on %s | status=%s",
            user.email, predict_date, result.status,
        )
        return result

    @staticmethod
    def _persist(
        user: User, predict_date: date, output, summary
    ) -> PredictionResult:
        """Upsert the PredictionResult record."""

        def dr(disease_name):
            obj = getattr(output, disease_name.lower(), None)
            if obj is None:
                return {
                    f"{disease_name.lower()}_score":     None,
                    f"{disease_name.lower()}_flag":      None,
                    f"{disease_name.lower()}_severity":  "",
                    f"{disease_name.lower()}_risk_prob": None,
                }
            return {
                f"{disease_name.lower()}_score":     obj.score,
                f"{disease_name.lower()}_flag":      obj.flag,
                f"{disease_name.lower()}_severity":  obj.severity,
                f"{disease_name.lower()}_risk_prob": obj.risk_prob,
            }

        fields = {}
        for disease in DISEASES:
            fields.update(dr(disease))

        result, _ = PredictionResult.objects.update_or_create(
            user=user,
            prediction_date=predict_date,
            defaults={
                "daily_summary":          summary,
                "model_version":          output.model_version,
                "symptom_burden_score":   output.symptom_burden_score,
                "feature_vector":         output.feature_vector,
                "raw_daily_data":         output.raw_daily_data,
                "days_of_data":           output.days_of_data,
                "data_completeness_pct":  output.data_completeness_pct,
                "status":                 output.status,
                "error_message":          output.error_message,
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
                "Minimal":  "✅",
                "Mild":     "🟡",
                "Moderate": "🟠",
                "Severe":   "🔴",
                "Extreme":  "🚨",
            }.get(worst_severity, "ℹ️")

            title = f"{severity_emoji} Your health risk scores are ready"
            body  = (
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
                    "prediction_id":  str(result.id),
                    "prediction_date": str(result.prediction_date),
                    "worst_disease":  worst_disease,
                    "worst_severity": worst_severity,
                    "action":         "open_prediction_report",
                },
            )

            result.patient_notified = True
            result.save(update_fields=["patient_notified"])

        except Exception as e:
            logger.error("Failed to notify patient %s: %s", user.email, e)

    @staticmethod
    def _escalate(user: User, result: PredictionResult):
        """Escalate to clinician / HCC / FHC for severe or extreme findings."""
        try:
            from apps.centers.signals import notify_center_of_critical_risk
            from apps.centers.models import RiskSeverity

            # Map our severity to centers.RiskSeverity
            severity_map = {
                "Severe":  RiskSeverity.SEVERE,
                "Extreme": RiskSeverity.VERY_SEVERE,
            }

            diseases_to_escalate = {
                "pcos":          (result.infertility_severity,   result.infertility_score),
                "maternal":      (result.dysmenorrhea_severity,  result.dysmenorrhea_score),
                "cardiovascular": (result.cvd_severity,          result.cvd_score),
            }

            for condition, (severity_str, score) in diseases_to_escalate.items():
                mapped = severity_map.get(severity_str)
                if mapped and score is not None:
                    notify_center_of_critical_risk(
                        patient=user,
                        condition=condition,
                        severity=mapped,
                        score=int((score or 0) * 100),
                    )

        except Exception as e:
            logger.error("Escalation failed for %s: %s", user.email, e)

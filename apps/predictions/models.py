"""
apps/predictions/models.py
═══════════════════════════
Prediction results from the ML pipeline.

One PredictionResult per (user, prediction_date).
Contains all 6 disease scores, flags, severity categories, and the
feature vector used — so we can audit every result forever.

Severity scale (from notebook):
  0.00 – 0.19  →  Minimal
  0.20 – 0.39  →  Mild
  0.40 – 0.59  →  Moderate
  0.60 – 0.79  →  Severe
  0.80 – 1.00  →  Extreme
"""
import uuid
from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator, MaxValueValidator

User = get_user_model()


class PredictionSeverity(models.TextChoices):
    MINIMAL  = "Minimal",  "Minimal  (0.00–0.19)"
    MILD     = "Mild",     "Mild     (0.20–0.39)"
    MODERATE = "Moderate", "Moderate (0.40–0.59)"
    SEVERE   = "Severe",   "Severe   (0.60–0.79)"
    EXTREME  = "Extreme",  "Extreme  (0.80–1.00)"


def score_field(**kwargs):
    return models.FloatField(
        null=True, blank=True,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        **kwargs,
    )


def prob_field(**kwargs):
    return models.FloatField(
        null=True, blank=True,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        **kwargs,
    )


class PredictionResult(models.Model):
    """
    Full ML output for one (user, date) after 28-day aggregation.
    6 diseases × (score, flag, severity, risk_prob) = 24 fields.
    """
    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user            = models.ForeignKey(User, on_delete=models.CASCADE, related_name="predictions")
    daily_summary   = models.OneToOneField(
        "health_checkin.DailyCheckinSummary",
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="prediction_result",
    )
    prediction_date = models.DateField()
    model_version   = models.CharField(max_length=50, default="v1.0")

    # ── Infertility / Anovulation ─────────────────────────────────────────────
    infertility_score    = score_field()
    infertility_flag     = models.BooleanField(null=True, blank=True)
    infertility_severity = models.CharField(max_length=10, choices=PredictionSeverity.choices, blank=True)
    infertility_risk_prob = prob_field()

    # ── Dysmenorrhea ──────────────────────────────────────────────────────────
    dysmenorrhea_score    = score_field()
    dysmenorrhea_flag     = models.BooleanField(null=True, blank=True)
    dysmenorrhea_severity = models.CharField(max_length=10, choices=PredictionSeverity.choices, blank=True)
    dysmenorrhea_risk_prob = prob_field()

    # ── PMDD ─────────────────────────────────────────────────────────────────
    pmdd_score    = score_field()
    pmdd_flag     = models.BooleanField(null=True, blank=True)
    pmdd_severity = models.CharField(max_length=10, choices=PredictionSeverity.choices, blank=True)
    pmdd_risk_prob = prob_field()

    # ── Type 2 Diabetes ────────────────────────────────────────────────────────
    t2d_score    = score_field()
    t2d_flag     = models.BooleanField(null=True, blank=True)
    t2d_severity = models.CharField(max_length=10, choices=PredictionSeverity.choices, blank=True)
    t2d_risk_prob = prob_field()

    # ── Cardiovascular Disease ────────────────────────────────────────────────
    cvd_score    = score_field()
    cvd_flag     = models.BooleanField(null=True, blank=True)
    cvd_severity = models.CharField(max_length=10, choices=PredictionSeverity.choices, blank=True)
    cvd_risk_prob = prob_field()

    # ── Endometrial Cancer ────────────────────────────────────────────────────
    endometrial_score    = score_field()
    endometrial_flag     = models.BooleanField(null=True, blank=True)
    endometrial_severity = models.CharField(max_length=10, choices=PredictionSeverity.choices, blank=True)
    endometrial_risk_prob = prob_field()

    # ── Overall Symptom Burden Score ──────────────────────────────────────────
    symptom_burden_score = score_field(help_text="SBS — weighted composite 0–10 normalised")

    # ── Audit: feature vector used for this prediction ─────────────────────────
    # Stored as JSON so clinicians can audit any result forever
    feature_vector   = models.JSONField(default=dict, help_text="28-day aggregated feature dict fed to model")
    raw_daily_data   = models.JSONField(default=list, help_text="List of daily row dicts used in aggregation")

    # ── Data quality ──────────────────────────────────────────────────────────
    days_of_data        = models.PositiveSmallIntegerField(default=0, help_text="How many of 28 days had data")
    data_completeness_pct = models.FloatField(default=0.0, help_text="days_of_data / 28 × 100")

    # ── Status ────────────────────────────────────────────────────────────────
    class PredictionStatus(models.TextChoices):
        SUCCESS     = "success",     "Success"
        PARTIAL     = "partial",     "Partial — some features missing"
        INSUFFICIENT = "insufficient", "Insufficient data (< 7 days)"
        ERROR       = "error",       "Pipeline error"

    status        = models.CharField(max_length=15, choices=PredictionStatus.choices, default=PredictionStatus.SUCCESS)
    error_message = models.TextField(blank=True)

    # ── Notification sent? ────────────────────────────────────────────────────
    patient_notified     = models.BooleanField(default=False)
    clinician_notified   = models.BooleanField(default=False)
    hcc_notified         = models.BooleanField(default=False)
    fhc_notified         = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label        = "predictions"
        unique_together  = [("user", "prediction_date")]
        ordering         = ["-prediction_date"]
        indexes = [
            models.Index(fields=["user", "prediction_date"]),
            models.Index(fields=["user", "status"]),
        ]
        verbose_name        = "Prediction Result"
        verbose_name_plural = "Prediction Results"

    def __str__(self):
        return f"Prediction | {self.prediction_date} | {self.user.email} | {self.status}"

    def get_highest_severity_disease(self) -> tuple[str, str]:
        """Return (disease_name, severity) for the most critical finding."""
        order = ["Extreme", "Severe", "Moderate", "Mild", "Minimal", ""]
        diseases = {
            "Infertility":  self.infertility_severity,
            "Dysmenorrhea": self.dysmenorrhea_severity,
            "PMDD":         self.pmdd_severity,
            "T2D":          self.t2d_severity,
            "CVD":          self.cvd_severity,
            "Endometrial":  self.endometrial_severity,
        }

        if all(sev == "" or sev is None for sev in diseases.values()):
            return "None", ""

        worst_sev = ""
        worst_dis = "None"
        for disease, sev in diseases.items():
            if sev and order.index(sev) < order.index(worst_sev if worst_sev else ""):
                worst_sev = sev
                worst_dis = disease
        return worst_dis, worst_sev

    def requires_escalation(self) -> bool:
        """True if any disease is Severe or Extreme → notify HCC/FHC."""
        critical = {"Severe", "Extreme"}
        return any(sev in critical for sev in [
            self.infertility_severity, self.dysmenorrhea_severity,
            self.pmdd_severity, self.t2d_severity,
            self.cvd_severity, self.endometrial_severity,
        ])

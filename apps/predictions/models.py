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
    MINIMAL = "Minimal", "Minimal  (0.00–0.19)"
    MILD = "Mild", "Mild     (0.20–0.39)"
    MODERATE = "Moderate", "Moderate (0.40–0.59)"
    SEVERE = "Severe", "Severe   (0.60–0.79)"
    EXTREME = "Extreme", "Extreme  (0.80–1.00)"


def score_field(**kwargs):
    return models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        **kwargs,
    )


def prob_field(**kwargs):
    return models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        **kwargs,
    )


class PredictionResult(models.Model):
    """
    Full ML output for one (user, date) after 28-day aggregation.
    6 diseases × (score, flag, severity, risk_prob) = 24 fields.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="predictions")
    daily_summary = models.OneToOneField(
        "health_checkin.DailyCheckinSummary",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prediction_result",
    )
    prediction_date = models.DateField()
    model_version = models.CharField(max_length=50, default="v1.0")

    # ── Infertility / Anovulation ─────────────────────────────────────────────
    infertility_score = score_field()
    infertility_flag = models.BooleanField(null=True, blank=True)
    infertility_severity = models.CharField(
        max_length=10, choices=PredictionSeverity.choices, blank=True
    )
    infertility_risk_prob = prob_field()

    # ── Dysmenorrhea ──────────────────────────────────────────────────────────
    dysmenorrhea_score = score_field()
    dysmenorrhea_flag = models.BooleanField(null=True, blank=True)
    dysmenorrhea_severity = models.CharField(
        max_length=10, choices=PredictionSeverity.choices, blank=True
    )
    dysmenorrhea_risk_prob = prob_field()

    # ── PMDD ─────────────────────────────────────────────────────────────────
    pmdd_score = score_field()
    pmdd_flag = models.BooleanField(null=True, blank=True)
    pmdd_severity = models.CharField(max_length=10, choices=PredictionSeverity.choices, blank=True)
    pmdd_risk_prob = prob_field()

    # ── Type 2 Diabetes ────────────────────────────────────────────────────────
    t2d_score = score_field()
    t2d_flag = models.BooleanField(null=True, blank=True)
    t2d_severity = models.CharField(max_length=10, choices=PredictionSeverity.choices, blank=True)
    t2d_risk_prob = prob_field()

    # ── Cardiovascular Disease ────────────────────────────────────────────────
    cvd_score = score_field()
    cvd_flag = models.BooleanField(null=True, blank=True)
    cvd_severity = models.CharField(max_length=10, choices=PredictionSeverity.choices, blank=True)
    cvd_risk_prob = prob_field()

    # ── Endometrial Cancer ────────────────────────────────────────────────────
    endometrial_score = score_field()
    endometrial_flag = models.BooleanField(null=True, blank=True)
    endometrial_severity = models.CharField(
        max_length=10, choices=PredictionSeverity.choices, blank=True
    )
    endometrial_risk_prob = prob_field()

    # ── Overall Symptom Burden Score ──────────────────────────────────────────
    symptom_burden_score = score_field(help_text="SBS — weighted composite 0–10 normalised")

    # ── Audit: feature vector used for this prediction ─────────────────────────
    # Stored as JSON so clinicians can audit any result forever
    feature_vector = models.JSONField(
        default=dict, help_text="28-day aggregated feature dict fed to model"
    )
    raw_daily_data = models.JSONField(
        default=list, help_text="List of daily row dicts used in aggregation"
    )

    # ── Data quality ──────────────────────────────────────────────────────────
    days_of_data = models.PositiveSmallIntegerField(
        default=0, help_text="How many of 28 days had data"
    )
    data_completeness_pct = models.FloatField(default=0.0, help_text="days_of_data / 28 × 100")

    # ── Status ────────────────────────────────────────────────────────────────
    class PredictionStatus(models.TextChoices):
        SUCCESS = "success", "Success"
        PARTIAL = "partial", "Partial — some features missing"
        INSUFFICIENT = "insufficient", "Insufficient data (< 7 days)"
        ERROR = "error", "Pipeline error"

    status = models.CharField(
        max_length=15, choices=PredictionStatus.choices, default=PredictionStatus.SUCCESS
    )
    error_message = models.TextField(blank=True)

    # ── Notification sent? ────────────────────────────────────────────────────
    patient_notified = models.BooleanField(default=False)
    clinician_notified = models.BooleanField(default=False)
    hcc_notified = models.BooleanField(default=False)
    fhc_notified = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "predictions"
        unique_together = [("user", "prediction_date")]
        ordering = ["-prediction_date"]
        indexes = [
            models.Index(fields=["user", "prediction_date"]),
            models.Index(fields=["user", "status"]),
        ]
        verbose_name = "Prediction Result"
        verbose_name_plural = "Prediction Results"

    def __str__(self):
        return f"Prediction | {self.prediction_date} | {self.user.email} | {self.status}"

    def get_highest_severity_disease(self) -> tuple[str, str]:
        """Return (disease_name, severity) for the most critical finding."""
        order = ["Extreme", "Severe", "Moderate", "Mild", "Minimal", ""]
        diseases = {
            "Infertility": self.infertility_severity,
            "Dysmenorrhea": self.dysmenorrhea_severity,
            "PMDD": self.pmdd_severity,
            "T2D": self.t2d_severity,
            "CVD": self.cvd_severity,
            "Endometrial": self.endometrial_severity,
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
        """
        True if any disease is Mild, Moderate, Severe, or Extreme.
        Minimal severity doesn't require escalation.

        Routing:
        - Mild/Moderate → PHCPatientRecord at patient's PHC
        - Severe/Very Severe → PatientCase at PHC's linked FMC
        """
        non_minimal = {"Mild", "Moderate", "Severe", "Extreme"}
        return any(
            sev in non_minimal
            for sev in [
                self.infertility_severity,
                self.dysmenorrhea_severity,
                self.pmdd_severity,
                self.t2d_severity,
                self.cvd_severity,
                self.endometrial_severity,
            ]
        )


class ComprehensivePredictionResult(models.Model):
    """
    Unified PCOS risk assessment combining all 4 data layers.

    This is the single source of truth for:
    - Patient Dashboard PCOS Risk Score
    - PCOSRiskScore page detailed breakdown
    - Escalation triggers to PHC/FMC

    Data Layers:
    1. Symptom Intensity (Active Layer) - from check-in data
    2. Menstrual (Active Layer) - from cycle tracking
    3. rPPG (Passive Layer) - from HRV measurements
    4. Mood (Active Layer) - from mood tracking
    """

    class RiskTier(models.TextChoices):
        LOW = "Low", "Low Risk"
        MODERATE = "Moderate", "Moderate Risk"
        HIGH = "High", "High Risk"
        CRITICAL = "Critical", "Critical Risk"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="comprehensive_predictions"
    )

    # Final unified score (0.0 - 1.0)
    final_risk_score = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="Final PCOS risk score from weighted ensemble",
    )
    risk_tier = models.CharField(
        max_length=10,
        choices=RiskTier.choices,
        default=RiskTier.LOW,
        help_text="Patient-facing risk tier label",
    )

    # PCOS-specific score (separate from overall risk)
    pcos_specific_score = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="PCOS-specific risk score with clinical rule adjustments",
    )

    # Per-disease scores from weighted ensemble
    per_disease_scores = models.JSONField(
        default=dict, help_text="Disease-specific scores: {'PCOS': 0.42, 'CVD': 0.55, ...}"
    )

    # Weights used for calculation
    weights_used = models.JSONField(
        default=dict, help_text="Final weights after data quality adjustment"
    )

    # Clinical rules triggered
    clinical_rules_triggered = models.JSONField(
        default=list, help_text="List of clinical rules that were applied"
    )

    # Full calculation breakdown
    calculation_breakdown = models.JSONField(
        default=dict, help_text="Full breakdown: base scores, boost applied, data quality"
    )

    # All model outputs (raw predictions from each layer)
    symptom_predictions = models.JSONField(
        default=dict, help_text="Raw predictions from symptom intensity model"
    )
    menstrual_predictions = models.JSONField(
        default=dict, help_text="Raw predictions from menstrual model"
    )
    rppg_predictions = models.JSONField(
        default=dict, help_text="Raw predictions from rPPG/HRV model"
    )
    mood_predictions = models.JSONField(default=dict, help_text="Raw predictions from mood model")

    # Data source tracking
    data_layers_used = models.JSONField(
        default=list,
        help_text="List of data layers that contributed: ['symptom', 'menstrual', 'rppg', 'mood']",
    )
    data_completeness_pct = models.PositiveSmallIntegerField(
        default=0, help_text="Percentage of data layers available (0-100)"
    )

    # Clinical severity flags (based on Rotterdam Criteria)
    severity_flags = models.JSONField(
        default=dict,
        help_text="""
        Clinical interpretation flags:
        - ovulatory_dysfunction: bool (cycle >35d OR CLV >7d)
        - hyperandrogenism: bool (high mFG or acne)
        - metabolic_stress: bool (low HRV and declining trend)
        - pcom_suspected: bool (combined indicators)
        """,
    )

    # Additional clinical context
    highest_risk_disease = models.CharField(
        max_length=50, blank=True, default="", help_text="Disease with highest risk score"
    )
    highest_risk_model = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="Model that produced the highest risk score",
    )

    # Notification status
    patient_notified = models.BooleanField(default=False)
    escalated_to_phc = models.BooleanField(default=False, help_text="PHC was notified")
    escalated_to_fmc = models.BooleanField(default=False, help_text="FMC was notified")

    # Timestamps
    computed_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "predictions"
        ordering = ["-computed_at"]
        verbose_name = "Comprehensive Prediction"
        verbose_name_plural = "Comprehensive Predictions"
        indexes = [
            models.Index(fields=["user", "-computed_at"]),
            models.Index(fields=["risk_tier"]),
            models.Index(fields=["final_risk_score"]),
        ]

    def __str__(self):
        return f"Comprehensive | {self.user.email} | {self.risk_tier} ({self.final_risk_score:.2f})"

    @classmethod
    def calculate_risk_tier(cls, score: float) -> str:
        """Convert numeric score to risk tier."""
        if score < 0.25:
            return cls.RiskTier.LOW
        elif score < 0.50:
            return cls.RiskTier.MODERATE
        elif score < 0.75:
            return cls.RiskTier.HIGH
        else:
            return cls.RiskTier.CRITICAL


class EnsembleWeightConfig(models.Model):
    """
    Stores ensemble weights per disease - configurable by clinical admin.

    This model allows clinical staff to adjust how much each ML model
    contributes to each disease's risk score.

    Default weights sum to 1.0 for each disease.
    """

    DISEASE_CHOICES = [
        ("PCOS", "PCOS"),
        ("CVD", "Cardiovascular Disease"),
        ("T2D", "Type 2 Diabetes"),
        ("Infertility", "Infertility"),
        ("Dysmenorrhea", "Dysmenorrhea"),
        ("Metabolic", "Metabolic Syndrome"),
        ("MentalHealth", "Mental Health"),
        ("Stroke", "Stroke Risk"),
        ("Endometrial", "Endometrial Cancer"),
    ]

    disease_name = models.CharField(
        max_length=50,
        unique=True,
        choices=DISEASE_CHOICES,
        help_text="Disease this weight configuration applies to",
    )

    # Model weights (must sum to 1.0)
    symptom_weight = models.FloatField(
        default=0.30,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="Weight for Symptom Intensity model (0.0-1.0)",
    )
    menstrual_weight = models.FloatField(
        default=0.25,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="Weight for Menstrual model (0.0-1.0)",
    )
    rppg_weight = models.FloatField(
        default=0.25,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="Weight for rPPG/HRV model (0.0-1.0)",
    )
    mood_weight = models.FloatField(
        default=0.20,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="Weight for Mood model (0.0-1.0)",
    )

    # Clinical rule amplifications
    rotterdam_2_criteria_boost = models.FloatField(
        default=0.05,
        validators=[MinValueValidator(0.0), MaxValueValidator(0.2)],
        help_text="Boost when 2 Rotterdam criteria are met (+0.05 default)",
    )
    rotterdam_3_criteria_boost = models.FloatField(
        default=0.10,
        validators=[MinValueValidator(0.0), MaxValueValidator(0.3)],
        help_text="Boost when all 3 Rotterdam criteria are met (+0.10 default)",
    )
    metabolic_reproductive_boost = models.FloatField(
        default=0.05,
        validators=[MinValueValidator(0.0), MaxValueValidator(0.2)],
        help_text="Boost when metabolic + reproductive both high (+0.05 default)",
    )
    mood_rppg_stress_boost = models.FloatField(
        default=0.03,
        validators=[MinValueValidator(0.0), MaxValueValidator(0.2)],
        help_text="Boost when mood + rPPG stress both moderate+ (+0.03 default)",
    )

    is_active = models.BooleanField(
        default=True, help_text="Whether this configuration is currently active"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "predictions"
        verbose_name = "Ensemble Weight Configuration"
        verbose_name_plural = "Ensemble Weight Configurations"

    def __str__(self):
        return f"{self.disease_name} - Symptom:{self.symptom_weight} Menstrual:{self.menstrual_weight} rPPG:{self.rppg_weight} Mood:{self.mood_weight}"

    def clean(self):
        """Validate that weights sum to 1.0"""
        from django.core.exceptions import ValidationError

        total = self.symptom_weight + self.menstrual_weight + self.rppg_weight + self.mood_weight
        if abs(total - 1.0) > 0.001:
            raise ValidationError(
                {"symptom_weight": f"Weights must sum to 1.0 (current sum: {total:.3f})"}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @classmethod
    def get_default_weights(cls) -> dict:
        """Return default weights if no config exists."""
        return {
            "PCOS": {"symptom": 0.30, "menstrual": 0.35, "rppg": 0.20, "mood": 0.15},
            "CVD": {"symptom": 0.20, "menstrual": 0.20, "rppg": 0.40, "mood": 0.20},
            "T2D": {"symptom": 0.25, "menstrual": 0.25, "rppg": 0.35, "mood": 0.15},
            "Infertility": {"symptom": 0.25, "menstrual": 0.40, "rppg": 0.20, "mood": 0.15},
            "Dysmenorrhea": {"symptom": 0.40, "menstrual": 0.35, "rppg": 0.10, "mood": 0.15},
            "Metabolic": {"symptom": 0.20, "menstrual": 0.20, "rppg": 0.45, "mood": 0.15},
            "MentalHealth": {"symptom": 0.20, "menstrual": 0.15, "rppg": 0.25, "mood": 0.40},
            "Stroke": {"symptom": 0.20, "menstrual": 0.20, "rppg": 0.35, "mood": 0.25},
            "Endometrial": {"symptom": 0.30, "menstrual": 0.45, "rppg": 0.15, "mood": 0.10},
        }

    def get_weight_dict(self) -> dict:
        """Return weights as a dict with model names as keys."""
        return {
            "symptom": self.symptom_weight,
            "menstrual": self.menstrual_weight,
            "rppg": self.rppg_weight,
            "mood": self.mood_weight,
        }

"""
apps/health_checkin/models.py
══════════════════════════════
All check-in session data, scored sub-scales, and raw inputs.

Architecture:
  CheckinSession          — one session per patient per check-in period (morning/evening)
  MorningCheckin          — fatigue, pelvic pressure, hyperalgesia (PSQ-3)
  EveningCheckin          — mastalgia, GAGS acne, bloating, unusual bleeding
  HirsutismMFGCheckin     — weekly; 9 body-area mFG scores → total
  DailyCheckinSummary     — aggregated daily roll-up used as one ML row

Session lifecycle:
  PENDING  → user started but not submitted
  PARTIAL  → some fields saved (app closed mid-way)
  COMPLETE → submitted and validated
  MISSED   → window closed without completion → triggers notification

One DailyCheckinSummary is assembled once BOTH morning + evening are COMPLETE.
Model inference runs on DailyCheckinSummary.
"""

import uuid
from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone

User = get_user_model()


# ─────────────────────────────────────────────────────────────────────────────
# Shared enums / constants
# ─────────────────────────────────────────────────────────────────────────────

class SessionPeriod(models.TextChoices):
    MORNING   = "morning",   "Morning"
    EVENING   = "evening",   "Evening"


class SessionStatus(models.TextChoices):
    PENDING  = "pending",  "Pending"
    PARTIAL  = "partial",  "Partial — saved mid-session"
    COMPLETE = "complete", "Complete"
    MISSED   = "missed",   "Missed — window expired"


class CyclePhase(models.TextChoices):
    MENSTRUAL   = "Menstrual",   "Menstrual"
    FOLLICULAR  = "Follicular",  "Follicular"
    OVULATORY   = "Ovulatory",   "Ovulatory"
    LUTEAL      = "Luteal",      "Luteal"
    UNKNOWN     = "Unknown",     "Unknown"


# ─────────────────────────────────────────────────────────────────────────────
# CheckinSession — one per (user, date, period)
# ─────────────────────────────────────────────────────────────────────────────

class CheckinSession(models.Model):
    """
    Parent record for each check-in attempt.
    UUID pk so mobile can create it offline and sync later.
    """
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user        = models.ForeignKey(User, on_delete=models.CASCADE, related_name="checkin_sessions")
    period      = models.CharField(max_length=12, choices=SessionPeriod.choices)
    status      = models.CharField(max_length=10, choices=SessionStatus.choices, default=SessionStatus.PENDING)
    checkin_date = models.DateField(default=timezone.localdate)

    # Cycle context — inferred from period tracking app or user-reported
    cycle_phase     = models.CharField(max_length=15, choices=CyclePhase.choices, default=CyclePhase.UNKNOWN)
    cycle_day       = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Day of menstrual cycle (1-35)")

    # HRV rPPG capture
    hrv_sdnn_ms     = models.FloatField(null=True, blank=True, help_text="SDNN in milliseconds from rPPG")
    hrv_rmssd_ms    = models.FloatField(null=True, blank=True)
    hrv_captured_at = models.DateTimeField(null=True, blank=True)
    hrv_skipped     = models.BooleanField(default=False)

    # Timestamps
    started_at      = models.DateTimeField(auto_now_add=True)
    submitted_at    = models.DateTimeField(null=True, blank=True)
    last_saved_at   = models.DateTimeField(auto_now=True)

    # Reminder tracking
    missed_reminder_sent = models.BooleanField(default=False)

    class Meta:
        app_label   = "health_checkin"
        unique_together = [("user", "checkin_date", "period")]
        ordering        = ["-checkin_date", "period"]
        indexes = [
            models.Index(fields=["user", "checkin_date"]),
            models.Index(fields=["user", "status"]),
        ]
        verbose_name        = "Check-in Session"
        verbose_name_plural = "Check-in Sessions"

    def __str__(self):
        return f"{self.user.email} | {self.checkin_date} | {self.period} | {self.status}"

    def mark_complete(self):
        self.status       = SessionStatus.COMPLETE
        self.submitted_at = timezone.now()
        self.save(update_fields=["status", "submitted_at", "last_saved_at"])

    def mark_missed(self):
        self.status = SessionStatus.MISSED
        self.save(update_fields=["status", "last_saved_at"])

    @property
    def is_complete(self):
        return self.status == SessionStatus.COMPLETE

    @property
    def is_missed(self):
        return self.status == SessionStatus.MISSED


# ─────────────────────────────────────────────────────────────────────────────
# Morning Check-in
# ─────────────────────────────────────────────────────────────────────────────

def vas_field(**kwargs):
    """0.0 – 10.0 Visual Analogue Scale field."""
    return models.FloatField(
        validators=[MinValueValidator(0.0), MaxValueValidator(10.0)],
        **kwargs,
    )


class MorningCheckin(models.Model):
    """
    Morning session inputs.
    Captured fields  →  model variables:
      fatigue_vas      →  Fatigue_MFI5_VAS
      pelvic_pressure  →  Pelvic_Pressure_VAS
      PSQ-3 trio       →  Painful_Touch_VAS (via hyperalgesia index)
    """
    id      = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.OneToOneField(
        CheckinSession, on_delete=models.CASCADE,
        related_name="morning_data",
        limit_choices_to={"period": SessionPeriod.MORNING},
    )

    # ── Fatigue (MFI-5 VAS proxy, 0–10) ──────────────────────────────────────
    fatigue_vas       = vas_field(null=True, blank=True)

    # ── Pelvic Pressure (0–10) ────────────────────────────────────────────────
    pelvic_pressure_vas = vas_field(null=True, blank=True)

    # ── Hyperalgesia / Painful Touch — PSQ-3 (each 0–10) ─────────────────────
    psq_skin_sensitivity     = vas_field(null=True, blank=True, help_text="Q1: Skin sensitivity to light touch")
    psq_muscle_pressure_pain = vas_field(null=True, blank=True, help_text="Q2: Muscle pressure pain")
    psq_body_tenderness      = vas_field(null=True, blank=True, help_text="Q3: Overall body tenderness")

    # ── Computed: Hyperalgesia Index ──────────────────────────────────────────
    # = (psq_skin + psq_muscle + psq_tenderness) / 3
    # Stored on save so we never re-compute in the prediction layer.
    hyperalgesia_index = models.FloatField(null=True, blank=True, help_text="PSQ-3 mean (0–10) = Painful_Touch_VAS")

    # ── Severity labels (computed on save) ────────────────────────────────────
    class HyperalgesiaLabel(models.TextChoices):
        NORMAL   = "Normal",   "Normal (0–3)"
        MILD     = "Mild",     "Mild (3.01–6)"
        MODERATE = "Moderate", "Moderate (6.01–9)"
        SEVERE   = "Severe",   "Severe (9.01–10)"

    hyperalgesia_severity = models.CharField(
        max_length=10, choices=HyperalgesiaLabel.choices,
        blank=True, null=True,
    )

    class Meta:
        app_label    = "health_checkin"
        verbose_name = "Morning Check-in"

    def __str__(self):
        return f"Morning | {self.session.checkin_date} | {self.session.user.email}"

    def compute_hyperalgesia(self):
        values = [
            self.psq_skin_sensitivity,
            self.psq_muscle_pressure_pain,
            self.psq_body_tenderness,
        ]
        filled = [v for v in values if v is not None]
        if not filled:
            self.hyperalgesia_index    = None
            self.hyperalgesia_severity = None
            return

        idx = sum(filled) / 3
        self.hyperalgesia_index = round(idx, 4)

        if idx <= 3.0:
            self.hyperalgesia_severity = self.HyperalgesiaLabel.NORMAL
        elif idx <= 6.0:
            self.hyperalgesia_severity = self.HyperalgesiaLabel.MILD
        elif idx <= 9.0:
            self.hyperalgesia_severity = self.HyperalgesiaLabel.MODERATE
        else:
            self.hyperalgesia_severity = self.HyperalgesiaLabel.SEVERE

    def save(self, *args, **kwargs):
        self.compute_hyperalgesia()
        super().save(*args, **kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# Evening Check-in
# ─────────────────────────────────────────────────────────────────────────────

class EveningCheckin(models.Model):
    """
    Evening session.
    Captured fields  →  model variables:
      breast_left/right     →  Breast_Soreness_VAS (via cyclic mastalgia score)
      GAGS acne scores      →  Acne_Severity_Likert (via GAGS formula)
      bloating_delta_cm     →  Bloating_Delta_cm
      unusual_bleeding      →  anovulatory_rate signal (period tracking)
    """
    id      = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.OneToOneField(
        CheckinSession, on_delete=models.CASCADE,
        related_name="evening_data",
        limit_choices_to={"period": SessionPeriod.EVENING},
    )

    # ── Cyclic Mastalgia (Breast Soreness VAS) ────────────────────────────────
    # Each side 0–10
    breast_left_vas  = vas_field(null=True, blank=True)
    breast_right_vas = vas_field(null=True, blank=True)

    # Side and quality — not used in model, saved for clinical history
    class MastalgiaSide(models.TextChoices):
        UNILATERAL = "Unilateral", "Unilateral"
        BILATERAL  = "Bilateral",  "Bilateral"

    class MastalgiaQuality(models.TextChoices):
        SHARP    = "Sharp",    "Sharp"
        DULL     = "Dull",     "Dull"
        PRESSURE = "Pressure", "Pressure"

    mastalgia_side    = models.CharField(max_length=12, choices=MastalgiaSide.choices, blank=True, null=True)
    mastalgia_quality = models.CharField(max_length=10, choices=MastalgiaQuality.choices, blank=True, null=True)

    # Computed: avg pain × NDBP weight → cyclic mastalgia score (0–20)
    # NDBP weight: 0 if avg==0, 1 if avg≤7, 2 if avg>7
    breast_pain_avg          = models.FloatField(null=True, blank=True)
    cyclic_mastalgia_score   = models.FloatField(null=True, blank=True, help_text="0–20, used as Breast_Soreness_VAS")
    breast_soreness_vas      = models.FloatField(null=True, blank=True, help_text="Normalised 0–10 for model")

    class MastalgiaSeverity(models.TextChoices):
        NONE     = "None",     "None"
        MILD     = "Mild",     "Mild (avg ≤ 3.5)"
        MODERATE = "Moderate", "Moderate (avg ≤ 7.0)"
        SEVERE   = "Severe",   "Severe (avg > 7.0)"

    mastalgia_severity = models.CharField(max_length=10, choices=MastalgiaSeverity.choices, blank=True, null=True)

    # ── GAGS Acne Score (each region 0–4 Likert) ──────────────────────────────
    # GAGS = (forehead×2)+(r_cheek×2)+(l_cheek×2)+(nose×1)+(chin×1)+(chest_back×3)
    acne_forehead    = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(4)])
    acne_right_cheek = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(4)])
    acne_left_cheek  = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(4)])
    acne_nose        = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(4)])
    acne_chin        = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(4)])
    acne_chest_back  = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(4)])

    # Computed GAGS total (max = 44 with cofactors: 2+2+2+1+1+3 = 11 × 4 = 44)
    gags_score        = models.PositiveSmallIntegerField(null=True, blank=True)
    # Normalised 0–3 Likert for model (gags_score / 44 * 3)
    acne_severity_likert = models.FloatField(null=True, blank=True, help_text="0–3.0 normalised for model")

    class AcneSeverity(models.TextChoices):
        NONE       = "None",       "None (0)"
        MILD       = "Mild",       "Mild (1–18)"
        MODERATE   = "Moderate",   "Moderate (19–30)"
        SEVERE     = "Severe",     "Severe (31–38)"
        VERY_SEVERE = "Very_Severe", "Very Severe (>38)"

    acne_severity_label = models.CharField(max_length=12, choices=AcneSeverity.choices, blank=True, null=True)

    # ── Bloating ──────────────────────────────────────────────────────────────
    bloating_delta_cm = models.FloatField(null=True, blank=True, help_text="Abdominal circumference Δ in cm")

    # ── Unusual bleeding flag ─────────────────────────────────────────────────
    unusual_bleeding = models.BooleanField(default=False, help_text="Any bleeding outside period window")

    class Meta:
        app_label    = "health_checkin"
        verbose_name = "Evening Check-in"

    def __str__(self):
        return f"Evening | {self.session.checkin_date} | {self.session.user.email}"

    def compute_mastalgia(self):
        left  = self.breast_left_vas  or 0.0
        right = self.breast_right_vas or 0.0
        avg   = (left + right) / 2
        self.breast_pain_avg = round(avg, 4)

        # NDBP weight
        if avg == 0:
            weight = 0
            self.mastalgia_severity = self.MastalgiaSeverity.NONE
        elif avg <= 3.5:
            weight = 1
            self.mastalgia_severity = self.MastalgiaSeverity.MILD
        elif avg <= 7.0:
            weight = 1
            self.mastalgia_severity = self.MastalgiaSeverity.MODERATE
        else:
            weight = 2
            self.mastalgia_severity = self.MastalgiaSeverity.SEVERE

        cms = avg * weight
        self.cyclic_mastalgia_score = round(cms, 4)
        # Normalise to 0–10 for model (max CMS = 10×2 = 20 → /2)
        self.breast_soreness_vas = round(min(cms / 2, 10.0), 4)

    def compute_gags(self):
        score = (
            self.acne_forehead    * 2 +
            self.acne_right_cheek * 2 +
            self.acne_left_cheek  * 2 +
            self.acne_nose        * 1 +
            self.acne_chin        * 1 +
            self.acne_chest_back  * 3
        )
        self.gags_score = score
        # Normalise to 0–3 Likert for model
        self.acne_severity_likert = round(score / 44 * 3, 4)

        if score == 0:
            self.acne_severity_label = self.AcneSeverity.NONE
        elif score <= 18:
            self.acne_severity_label = self.AcneSeverity.MILD
        elif score <= 30:
            self.acne_severity_label = self.AcneSeverity.MODERATE
        elif score <= 38:
            self.acne_severity_label = self.AcneSeverity.SEVERE
        else:
            self.acne_severity_label = self.AcneSeverity.VERY_SEVERE

    def save(self, *args, **kwargs):
        self.compute_mastalgia()
        self.compute_gags()
        super().save(*args, **kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# Hirsutism mFG Weekly Check-in
# ─────────────────────────────────────────────────────────────────────────────

class HirsutismMFGCheckin(models.Model):
    """
    Weekly Modified Ferriman-Gallwey (mFG) assessment.
    9 body areas, each scored 0–4.
    Total mFG = sum(9 areas), max = 36.

    Interpretation:
      0–7   → Normal
      8–16  → Mild Hirsutism
      17–24 → Moderate Hirsutism
      ≥25   → Severe Hirsutism

    The 28-day mean of mfg_total_score feeds into Hirsutism_mFG_Score
    for the ML model.
    """
    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="mfg_checkins")
    assessed_date = models.DateField(default=timezone.localdate)

    # 9 body areas (0–4 each)
    mfg_upper_lip    = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(4)], help_text="Upper lip")
    mfg_chin         = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(4)], help_text="Chin")
    mfg_chest        = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(4)], help_text="Chest")
    mfg_upper_back   = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(4)], help_text="Upper back")
    mfg_lower_back   = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(4)], help_text="Lower back")
    mfg_upper_abdomen = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(4)], help_text="Upper abdomen")
    mfg_lower_abdomen = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(4)], help_text="Lower abdomen")
    mfg_upper_arm    = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(4)], help_text="Upper arm")
    mfg_thigh        = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(4)], help_text="Thigh")

    # Computed total (0–36)
    mfg_total_score  = models.PositiveSmallIntegerField(null=True, blank=True)

    class MFGSeverity(models.TextChoices):
        NORMAL   = "Normal",   "Normal (0–7)"
        MILD     = "Mild",     "Mild (8–16)"
        MODERATE = "Moderate", "Moderate (17–24)"
        SEVERE   = "Severe",   "Severe (≥25)"

    mfg_severity = models.CharField(max_length=10, choices=MFGSeverity.choices, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label        = "health_checkin"
        unique_together  = [("user", "assessed_date")]
        ordering         = ["-assessed_date"]
        verbose_name     = "Hirsutism mFG Check-in"
        verbose_name_plural = "Hirsutism mFG Check-ins"

    def __str__(self):
        return f"mFG | {self.assessed_date} | {self.user.email} | score={self.mfg_total_score}"

    def compute_mfg(self):
        total = (
            self.mfg_upper_lip + self.mfg_chin + self.mfg_chest +
            self.mfg_upper_back + self.mfg_lower_back +
            self.mfg_upper_abdomen + self.mfg_lower_abdomen +
            self.mfg_upper_arm + self.mfg_thigh
        )
        self.mfg_total_score = total

        if total <= 7:
            self.mfg_severity = self.MFGSeverity.NORMAL
        elif total <= 16:
            self.mfg_severity = self.MFGSeverity.MILD
        elif total <= 24:
            self.mfg_severity = self.MFGSeverity.MODERATE
        else:
            self.mfg_severity = self.MFGSeverity.SEVERE

    def save(self, *args, **kwargs):
        self.compute_mfg()
        super().save(*args, **kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# Daily Checkin Summary — the ML row
# ─────────────────────────────────────────────────────────────────────────────

class DailyCheckinSummary(models.Model):
    """
    One row per (user, date). Assembled after BOTH morning + evening are complete.
    This is the direct input to the ML pipeline.

    Columns mirror the notebook's patient aggregation:
      Pelvic_Pressure_VAS, Fatigue_MFI5_VAS, Painful_Touch_VAS,
      Breast_Soreness_VAS, Acne_Severity_Likert, Hirsutism_mFG_Score,
      Bloating_Delta_cm, Cycle_Phase, PCOS_Status_Label (from onboarding)

    The 28-day aggregation (means, slopes, phase splits) is done in
    the prediction service before calling the ML model.
    """
    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="daily_summaries")

    summary_date = models.DateField(default=timezone.localdate)

    # Source session references
    morning_session   = models.ForeignKey(
        CheckinSession, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="morning_summary",
        limit_choices_to={"period": SessionPeriod.MORNING},
    )
    evening_session   = models.ForeignKey(
        CheckinSession, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="evening_summary",
        limit_choices_to={"period": SessionPeriod.EVENING},
    )

    # ── ML Model input variables (notebook names) ─────────────────────────────
    # VAS fields averaged across morning where applicable
    pelvic_pressure_vas   = models.FloatField(null=True, blank=True, help_text="Pelvic_Pressure_VAS — from morning")
    fatigue_mfi5_vas      = models.FloatField(null=True, blank=True, help_text="Fatigue_MFI5_VAS — from morning")
    painful_touch_vas     = models.FloatField(null=True, blank=True, help_text="Painful_Touch_VAS — from morning PSQ-3")
    breast_soreness_vas   = models.FloatField(null=True, blank=True, help_text="Breast_Soreness_VAS — evening mastalgia normalised")
    acne_severity_likert  = models.FloatField(null=True, blank=True, help_text="Acne_Severity_Likert 0–3 from GAGS")
    hirsutism_mfg_score   = models.FloatField(null=True, blank=True, help_text="Hirsutism_mFG_Score — most recent mFG total")
    bloating_delta_cm     = models.FloatField(null=True, blank=True, help_text="Bloating_Delta_cm — evening")

    # Cycle context
    cycle_phase = models.CharField(max_length=15, choices=CyclePhase.choices, default=CyclePhase.UNKNOWN)
    cycle_day   = models.PositiveSmallIntegerField(null=True, blank=True)

    # HRV (from rPPG session, either morning or evening)
    hrv_sdnn_ms  = models.FloatField(null=True, blank=True)
    hrv_rmssd_ms = models.FloatField(null=True, blank=True)

    # Unusual bleeding flag (feeds anovulatory_rate in the full model)
    unusual_bleeding = models.BooleanField(default=False)

    # Completeness flags
    morning_complete   = models.BooleanField(default=False)
    evening_complete   = models.BooleanField(default=False)

    # Whether prediction has been run on this row
    prediction_run   = models.BooleanField(default=False)
    prediction_run_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label       = "health_checkin"
        unique_together = [("user", "summary_date")]
        ordering        = ["-summary_date"]
        indexes = [
            models.Index(fields=["user", "summary_date"]),
            models.Index(fields=["user", "prediction_run"]),
        ]
        verbose_name        = "Daily Check-in Summary"
        verbose_name_plural = "Daily Check-in Summaries"

    def __str__(self):
        return f"DailySummary | {self.summary_date} | {self.user.email}"

    @property
    def is_ready_for_prediction(self):
        """Both morning and evening must be complete."""
        return self.morning_complete and self.evening_complete

    @property
    def completeness_pct(self):
        done = sum([self.morning_complete, self.evening_complete])
        return round(done / 2 * 100)


# ─────────────────────────────────────────────────────────────────────────────
# CheckinStreak — gamification / adherence tracking
# ─────────────────────────────────────────────────────────────────────────────

class CheckinStreak(models.Model):
    """
    Tracks consecutive days with at least morning + evening complete.
    Used for adherence notifications and UI streak display.
    """
    user             = models.OneToOneField(User, on_delete=models.CASCADE, related_name="checkin_streak")
    current_streak   = models.PositiveIntegerField(default=0)
    longest_streak   = models.PositiveIntegerField(default=0)
    last_complete_date = models.DateField(null=True, blank=True)
    total_days_logged  = models.PositiveIntegerField(default=0)
    updated_at         = models.DateTimeField(auto_now=True)

    class Meta:
        app_label    = "health_checkin"
        verbose_name = "Check-in Streak"

    def __str__(self):
        return f"Streak({self.user.email}) = {self.current_streak} days"

"""
apps/onboarding/models.py
──────────────────────────
Onboarding data is stored as a single OnboardingProfile per user.
Each step's data is structured as nested classes to mirror the Flutter UI.
Step 6 (rPPG baseline) is intentionally excluded from persistent storage
for now — it will be wired to the signal-processing pipeline later.
"""
import uuid
from django.db import models
from django.conf import settings


class OnboardingProfile(models.Model):
    """
    One-to-one with User. Persists all onboarding steps.
    Partially completed profiles are allowed (step tracked on User.onboarding_step).
    """
 
    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False) 
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="onboarding_profile")

    # ── Step 1: Personal Info ─────────────────────────────────────────────────
    full_name = models.CharField(max_length=255, blank=True)
    age       = models.PositiveSmallIntegerField(null=True, blank=True)

    class Ethnicity(models.TextChoices):
        WHITE            = "white",          "White/Caucasian"
        BLACK            = "black",          "Black/African American"
        HISPANIC         = "hispanic",       "Hispanic/Latino"
        ASIAN            = "asian",          "Asian"
        SOUTH_ASIAN      = "south_asian",    "South Asian"
        MIDDLE_EASTERN   = "middle_eastern", "Middle Eastern"
        MIXED            = "mixed",          "Mixed/Other"
        PREFER_NOT       = "prefer_not",     "Prefer not to say"

    ethnicity = models.CharField(
        max_length=30, choices=Ethnicity.choices, blank=True
    )

    # ── Step 2: Physical Measurements ────────────────────────────────────────
    height_cm  = models.FloatField(null=True, blank=True)
    weight_kg  = models.FloatField(null=True, blank=True)
    bmi        = models.FloatField(null=True, blank=True)   # computed on save

    # ── Step 3: Skin Changes ──────────────────────────────────────────────────
    has_skin_changes = models.BooleanField(null=True, blank=True)  # Acanthosis Nigricans

    # ── Step 4: Menstrual History ─────────────────────────────────────────────
    cycle_length_days  = models.PositiveSmallIntegerField(null=True, blank=True)
    periods_per_year   = models.PositiveSmallIntegerField(null=True, blank=True)

    class CycleRegularity(models.TextChoices):
        REGULAR   = "regular",   "Regular"
        IRREGULAR = "irregular", "Irregular"

    cycle_regularity = models.CharField(
        max_length=15, choices=CycleRegularity.choices, blank=True
    )

    # ── Step 5: Wearable ──────────────────────────────────────────────────────
    class WearableDevice(models.TextChoices):
        APPLE_WATCH = "apple_watch", "Apple Watch"
        FITBIT      = "fitbit",      "Fitbit"
        GARMIN      = "garmin",      "Garmin"
        OURA_RING   = "oura_ring",   "Oura Ring"
        NONE        = "none",        "None / Skip"

    selected_wearable = models.CharField(
        max_length=20, choices=WearableDevice.choices, blank=True
    )

    # ── Step 6: rPPG baseline (placeholder) ──────────────────────────────────
    # Full rPPG signal processing will be wired to a separate pipeline.
    rppg_baseline_captured = models.BooleanField(default=False)
    rppg_captured_at       = models.DateTimeField(null=True, blank=True)

    # ── Step 7: PHC Registration (patients only) ──────────────────────────────
    state = models.CharField(max_length=100, blank=True)
    lga   = models.CharField(max_length=100, blank=True)
    
    registered_hcc = models.ForeignKey(
        "centers.HealthCareCenter",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="registered_patients",
        help_text=(
            "The Primary Health Centre this patient is registered with. "
            "Set during onboarding (patient picks from nearby PHCs filtered by state/LGA), "
            "or auto-set when PHC staff registers a walk-in patient. "
            "This is the patient's permanent home facility for Low/Moderate escalation routing."
        ),
    )

    # ── Meta ──────────────────────────────────────────────────────────────────
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Onboarding Profile"

    def __str__(self):
        return f"Onboarding({self.user.email})"

    def compute_bmi(self) -> float | None:
        if self.height_cm and self.weight_kg and self.height_cm > 0:
            return round(self.weight_kg / ((self.height_cm / 100) ** 2), 1)
        return None

    def save(self, *args, **kwargs):
        self.bmi = self.compute_bmi()
        super().save(*args, **kwargs)

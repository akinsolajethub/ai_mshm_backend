"""
apps/onboarding/admin.py
─────────────────────────
Django admin for onboarding profiles.

Platform Admin can view and edit onboarding profiles here.
This is particularly useful for:
  - Manually setting a patient's registered_hcc after a CHANGE_PHC request is approved
  - Debugging incomplete onboarding
  - Viewing patient location data (state/lga) for support purposes
"""
from django.contrib import admin
from .models import OnboardingProfile


@admin.register(OnboardingProfile)
class OnboardingProfileAdmin(admin.ModelAdmin):
    list_display    = (
        "user", "age", "ethnicity", "bmi",
        "state", "lga", "registered_hcc",
        "rppg_baseline_captured", "updated_at",
    )
    list_filter     = ("ethnicity", "cycle_regularity", "rppg_baseline_captured", "registered_hcc__state")
    search_fields   = ("user__email", "full_name", "state", "lga")
    raw_id_fields   = ("user", "registered_hcc")
    readonly_fields = ("bmi", "created_at", "updated_at")

    fieldsets = (
        ("Personal Info (Step 1)", {
            "fields": ("user", "full_name", "age", "ethnicity"),
        }),
        ("Physical (Step 2)", {
            "fields": ("height_cm", "weight_kg", "bmi"),
        }),
        ("Clinical (Step 3)", {
            "fields": ("has_skin_changes",),
        }),
        ("Menstrual History (Step 4)", {
            "fields": ("cycle_length_days", "periods_per_year", "cycle_regularity"),
        }),
        ("Wearable (Step 5)", {
            "fields": ("selected_wearable",),
        }),
        ("rPPG Baseline (Step 6)", {
            "fields": ("rppg_baseline_captured", "rppg_captured_at"),
        }),
        ("PHC Registration (Step 7)", {
            "fields": ("state", "lga", "registered_hcc"),
            "description": (
                "registered_hcc is set by the patient during onboarding step 7, "
                "or auto-set when PHC staff registers a walk-in patient. "
                "To apply a CHANGE_PHC request, update registered_hcc here."
            ),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )
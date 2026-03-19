"""
apps/onboarding/serializers.py
───────────────────────────────
Each step has its own serializer. This keeps validation focused
and lets the frontend submit steps independently.

STEP 7 — PHC Registration:
  Step7PHCRegistrationSerializer accepts state, lga, and registered_hcc.
  registered_hcc is optional (nullable) — patient can skip.

ONBOARDING PROFILE READ:
  OnboardingProfileSerializer returns the full profile including:
    - registered_hcc_detail: minimal PHC info (name, code, state, lga)
    - escalation_fmc_detail: the FMC this patient would escalate to
      (read-only, derived from PHC.escalates_to or state fallback)
      This is what the patient sees in their P9 profile screen as "Your FMC".
"""
from rest_framework import serializers
from .models import OnboardingProfile


class Step1PersonalInfoSerializer(serializers.ModelSerializer):
    class Meta:
        model  = OnboardingProfile
        fields = ["full_name", "age", "ethnicity"]

    def validate_age(self, value):
        if value is not None and not (10 <= value <= 120):
            raise serializers.ValidationError("Age must be between 10 and 120.")
        return value


class Step2PhysicalMeasurementsSerializer(serializers.ModelSerializer):
    bmi = serializers.FloatField(read_only=True)

    class Meta:
        model  = OnboardingProfile
        fields = ["height_cm", "weight_kg", "bmi"]

    def validate_height_cm(self, value):
        if value is not None and not (50 <= value <= 300):
            raise serializers.ValidationError("Height must be between 50 and 300 cm.")
        return value

    def validate_weight_kg(self, value):
        if value is not None and not (20 <= value <= 500):
            raise serializers.ValidationError("Weight must be between 20 and 500 kg.")
        return value


class Step3SkinChangesSerializer(serializers.ModelSerializer):
    class Meta:
        model  = OnboardingProfile
        fields = ["has_skin_changes"]

    def validate_has_skin_changes(self, value):
        if value is None:
            raise serializers.ValidationError("Please select Yes or No.")
        return value


class Step4MenstrualHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model  = OnboardingProfile
        fields = ["cycle_length_days", "periods_per_year", "cycle_regularity"]

    def validate_cycle_length_days(self, value):
        if value is not None and not (1 <= value <= 90):
            raise serializers.ValidationError("Cycle length must be between 1 and 90 days.")
        return value

    def validate_periods_per_year(self, value):
        if value is not None and not (0 <= value <= 14):
            raise serializers.ValidationError("Periods per year must be between 0 and 14.")
        return value


class Step5WearableSerializer(serializers.ModelSerializer):
    class Meta:
        model  = OnboardingProfile
        fields = ["selected_wearable"]


class Step6RppgSerializer(serializers.Serializer):
    """
    Placeholder — the real rPPG pipeline will receive a video blob.
    For now we just flag the baseline as captured.
    """
    baseline_captured = serializers.BooleanField()


class Step7PHCRegistrationSerializer(serializers.ModelSerializer):
    """
    Patient selects their nearest PHC during onboarding (or from P9 profile settings).

    The registered_hcc field is optional — patient can skip this step.
    Frontend should first call GET /api/v1/centers/phc/?state=X&lga=Y
    to get filtered options, then submit the chosen UUID here.

    registered_hcc_detail: returns the selected PHC's name, code, state, lga
    as a read-only nested object so the frontend can confirm the selection.
    """
    registered_hcc_detail = serializers.SerializerMethodField(
        help_text="Read-only. Returns the selected PHC's basic details after saving.",
    )

    class Meta:
        model  = OnboardingProfile
        fields = ["state", "lga", "registered_hcc", "registered_hcc_detail"]
        extra_kwargs = {
            "registered_hcc": {
                "required":   False,
                "allow_null": True,
                "help_text":  "UUID of the selected PHC. Null if patient skips this step.",
            },
            "state": {
                "required": False,
                "help_text": "Patient's state e.g. 'Lagos'. Used to filter nearby PHCs.",
            },
            "lga": {
                "required": False,
                "help_text": "Patient's LGA e.g. 'Surulere'. Used to filter nearby PHCs.",
            },
        }

    def get_registered_hcc_detail(self, obj):
        if not obj.registered_hcc:
            return None
        hcc = obj.registered_hcc
        return {
            "id":    str(hcc.id),
            "name":  hcc.name,
            "code":  hcc.code,
            "state": hcc.state,
            "lga":   hcc.lga,
        }


class OnboardingProfileSerializer(serializers.ModelSerializer):
    """
    Full read serializer — returned by GET /api/v1/onboarding/profile/
    and after OnboardingCompleteView.

    KEY FIELDS FOR PATIENT PROFILE (P9 screen):
      registered_hcc_detail  — the patient's home PHC (they can change this)
      escalation_fmc_detail  — the FMC this patient escalates to (read-only,
                                derived from PHC.escalates_to chain)

    The frontend shows both on the P9 profile screen so the patient can see:
      "Your home PHC: Surulere Primary Health Centre"
      "Your escalation FMC: Lagos University Teaching Hospital"

    The patient CANNOT directly change the FMC — it is determined by their PHC.
    If they want to change their FMC, they must submit a ChangeRequest.
    """
    bmi                   = serializers.FloatField(read_only=True)
    registered_hcc_detail = serializers.SerializerMethodField()
    escalation_fmc_detail = serializers.SerializerMethodField()

    class Meta:
        model  = OnboardingProfile
        fields = [
            # Steps 1–5
            "full_name", "age", "ethnicity",
            "height_cm", "weight_kg", "bmi",
            "has_skin_changes",
            "cycle_length_days", "periods_per_year", "cycle_regularity",
            "selected_wearable",
            # Step 6
            "rppg_baseline_captured", "rppg_captured_at",
            # Step 7 — PHC Registration
            "state", "lga", "registered_hcc",
            "registered_hcc_detail", "escalation_fmc_detail",
            # Meta
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "bmi", "rppg_captured_at",
            "registered_hcc_detail", "escalation_fmc_detail",
            "created_at", "updated_at",
        ]

    def get_registered_hcc_detail(self, obj):
        """
        Returns the patient's registered PHC details.
        Shown on P9 profile screen as 'Your home health centre'.
        Patient can change this via PATCH /api/v1/onboarding/step/7/
        """
        if not obj.registered_hcc:
            return None
        hcc = obj.registered_hcc
        return {
            "id":    str(hcc.id),
            "name":  hcc.name,
            "code":  hcc.code,
            "state": hcc.state,
            "lga":   hcc.lga,
        }

    def get_escalation_fmc_detail(self, obj):
        """
        Returns the FMC this patient would escalate to if their score reaches Severe.
        Derived from: registered_hcc.get_escalation_fmc()
        Read-only — patient cannot change this directly.
        Shown on P9 profile screen as 'Your escalation centre'.

        Returns null if:
          - Patient has no registered PHC
          - PHC has no escalates_to and no FMC in the same state
        """
        if not obj.registered_hcc:
            return None
        try:
            fmc = obj.registered_hcc.get_escalation_fmc()
            if not fmc:
                return None
            return {
                "id":    str(fmc.id),
                "name":  fmc.name,
                "code":  fmc.code,
                "state": fmc.state,
            }
        except Exception:
            return None
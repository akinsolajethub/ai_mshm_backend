"""
apps/health_checkin/serializers.py
════════════════════════════════════
One serializer per check-in screen, matching the Flutter UI exactly.
"""
from rest_framework import serializers
from .models import (
    CheckinSession, MorningCheckin, EveningCheckin, 
    HirsutismMFGCheckin, DailyCheckinSummary,
)


# ─────────────────────────────────────────────────────────────────────────────
# Session
# ─────────────────────────────────────────────────────────────────────────────

class CheckinSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model  = CheckinSession
        fields = [
            "id", "period", "status", "checkin_date",
            "cycle_phase", "cycle_day",
            "hrv_sdnn_ms", "hrv_rmssd_ms", "hrv_captured_at", "hrv_skipped",
            "started_at", "submitted_at", "last_saved_at",
        ]
        read_only_fields = ["id", "started_at", "submitted_at", "last_saved_at"]


# ─────────────────────────────────────────────────────────────────────────────
# Morning
# ─────────────────────────────────────────────────────────────────────────────

class MorningCheckinSerializer(serializers.ModelSerializer):
    """
    Used for both save-in-progress (all optional) and final submit.
    Computed fields (hyperalgesia_index, hyperalgesia_severity) are read-only.
    """
    class Meta:
        model  = MorningCheckin
        fields = [
            "id",
            # Raw inputs
            "fatigue_vas",
            "pelvic_pressure_vas",
            "psq_skin_sensitivity",
            "psq_muscle_pressure_pain",
            "psq_body_tenderness",
            # Computed
            "hyperalgesia_index",
            "hyperalgesia_severity",
        ]
        read_only_fields = ["id", "hyperalgesia_index", "hyperalgesia_severity"]

    def validate_fatigue_vas(self, v):
        if v is not None and not (0 <= v <= 10):
            raise serializers.ValidationError("Fatigue VAS must be between 0 and 10.")
        return v

    def validate_pelvic_pressure_vas(self, v):
        if v is not None and not (0 <= v <= 10):
            raise serializers.ValidationError("Pelvic pressure VAS must be between 0 and 10.")
        return v


class MorningCheckinPartialSerializer(MorningCheckinSerializer):
    """
    Auto-save (partial=True) — mobile calls this every slider change.
    All fields are optional.
    """
    class Meta(MorningCheckinSerializer.Meta):
        extra_kwargs = {f: {"required": False} for f in MorningCheckinSerializer.Meta.fields}


# ─────────────────────────────────────────────────────────────────────────────
# Evening
# ─────────────────────────────────────────────────────────────────────────────

class EveningCheckinSerializer(serializers.ModelSerializer):
    """
    Mirrors EveningCheckinScreen exactly.
    Computed: breast_pain_avg, cyclic_mastalgia_score, breast_soreness_vas,
              mastalgia_severity, gags_score, acne_severity_likert, acne_severity_label.
    """
    class Meta:
        model  = EveningCheckin
        fields = [
            "id",
            # Mastalgia
            "breast_left_vas", "breast_right_vas",
            "mastalgia_side", "mastalgia_quality",
            # Mastalgia computed
            "breast_pain_avg", "cyclic_mastalgia_score",
            "breast_soreness_vas", "mastalgia_severity",
            # GAGS acne regions
            "acne_forehead", "acne_right_cheek", "acne_left_cheek",
            "acne_nose", "acne_chin", "acne_chest_back",
            # GAGS computed
            "gags_score", "acne_severity_likert", "acne_severity_label",
            # Bloating
            "bloating_delta_cm",
            # Unusual bleeding
            "unusual_bleeding",
        ]
        read_only_fields = [
            "id",
            "breast_pain_avg", "cyclic_mastalgia_score",
            "breast_soreness_vas", "mastalgia_severity",
            "gags_score", "acne_severity_likert", "acne_severity_label",
        ]

    def validate_acne_forehead(self, v):
        if not (0 <= v <= 4):
            raise serializers.ValidationError("Acne regional grade must be 0–4.")
        return v

    # Repeat for each acne region
    validate_acne_right_cheek = validate_acne_forehead
    validate_acne_left_cheek  = validate_acne_forehead
    validate_acne_nose         = validate_acne_forehead
    validate_acne_chin         = validate_acne_forehead
    validate_acne_chest_back   = validate_acne_forehead


# ─────────────────────────────────────────────────────────────────────────────
# mFG Hirsutism
# ─────────────────────────────────────────────────────────────────────────────

class HirsutismMFGSerializer(serializers.ModelSerializer):
    """
    9 body areas + computed total and severity.
    Each area 0–4.
    """
    class Meta:
        model  = HirsutismMFGCheckin
        fields = [
            "id", "assessed_date",
            # 9 body areas
            "mfg_upper_lip", "mfg_chin", "mfg_chest",
            "mfg_upper_back", "mfg_lower_back",
            "mfg_upper_abdomen", "mfg_lower_abdomen",
            "mfg_upper_arm", "mfg_thigh",
            # Computed
            "mfg_total_score", "mfg_severity",
        ]
        read_only_fields = ["id", "mfg_total_score", "mfg_severity"]

    def validate(self, attrs):
        for field in [
            "mfg_upper_lip", "mfg_chin", "mfg_chest",
            "mfg_upper_back", "mfg_lower_back",
            "mfg_upper_abdomen", "mfg_lower_abdomen",
            "mfg_upper_arm", "mfg_thigh",
        ]:
            v = attrs.get(field, 0)
            if not (0 <= v <= 4):
                raise serializers.ValidationError({field: "mFG area score must be 0–4."})
        return attrs


# ─────────────────────────────────────────────────────────────────────────────
# Daily Summary (read-only — assembled by service)
# ─────────────────────────────────────────────────────────────────────────────

class DailyCheckinSummarySerializer(serializers.ModelSerializer):
    completeness_pct    = serializers.IntegerField(read_only=True)
    is_ready_for_prediction = serializers.BooleanField(read_only=True)

    class Meta:
        model  = DailyCheckinSummary
        fields = [
            "id", "summary_date",
            "pelvic_pressure_vas", "fatigue_mfi5_vas", "painful_touch_vas",
            "breast_soreness_vas", "acne_severity_likert",
            "hirsutism_mfg_score", "bloating_delta_cm",
            "cycle_phase", "cycle_day",
            "hrv_sdnn_ms", "hrv_rmssd_ms",
            "unusual_bleeding",
            "morning_complete", "evening_complete",
            "completeness_pct", "is_ready_for_prediction",
            "prediction_run", "prediction_run_at",
            "created_at", "updated_at",
        ]
        read_only_fields = fields


# ─────────────────────────────────────────────────────────────────────────────
# HRV Submit
# ─────────────────────────────────────────────────────────────────────────────

class HRVSubmitSerializer(serializers.Serializer):
    """Submitted after rPPG camera session completes."""
    session_id   = serializers.UUIDField()
    hrv_sdnn_ms  = serializers.FloatField(min_value=0, max_value=500, required=False)
    hrv_rmssd_ms = serializers.FloatField(min_value=0, max_value=500, required=False)
    skipped      = serializers.BooleanField(default=False)


# ─────────────────────────────────────────────────────────────────────────────
# Checkin Status (quick endpoint for UI to know today's state)
# ─────────────────────────────────────────────────────────────────────────────

class TodayStatusSerializer(serializers.Serializer):
    """What the dashboard uses to show today's check-in progress."""
    date              = serializers.DateField()
    morning_status    = serializers.CharField()
    evening_status    = serializers.CharField()
    morning_session_id   = serializers.UUIDField(allow_null=True)
    evening_session_id   = serializers.UUIDField(allow_null=True)
    completeness_pct  = serializers.IntegerField()
    streak_days       = serializers.IntegerField()
    missed_yesterday_morning = serializers.BooleanField()
    missed_yesterday_evening = serializers.BooleanField()

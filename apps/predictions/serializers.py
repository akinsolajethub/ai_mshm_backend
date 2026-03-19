"""
apps/predictions/serializers.py
"""
from rest_framework import serializers
from .models import PredictionResult, PredictionSeverity


class DiseaseResultSerializer(serializers.Serializer):
    score      = serializers.FloatField()
    flag       = serializers.BooleanField()
    severity   = serializers.CharField()
    risk_prob  = serializers.FloatField()
    message    = serializers.CharField()


SEVERITY_MESSAGES = {
    "Minimal":  "No significant clinical concern. Keep up your healthy habits.",
    "Mild":     "Low-level signal detected. Monitor symptoms and maintain lifestyle changes.",
    "Moderate": "Elevated risk detected. A medical review is recommended.",
    "Severe":   "High risk detected. Please consult a specialist soon.",
    "Extreme":  "Critical risk level. Immediate clinical intervention is strongly advised.",
    "":         "Insufficient data for assessment.",
}


class PredictionResultSerializer(serializers.ModelSerializer):
    # Flattened disease objects for frontend
    infertility  = serializers.SerializerMethodField()
    dysmenorrhea = serializers.SerializerMethodField()
    pmdd         = serializers.SerializerMethodField()
    t2d          = serializers.SerializerMethodField()
    cvd          = serializers.SerializerMethodField()
    endometrial  = serializers.SerializerMethodField()
    highest_risk = serializers.SerializerMethodField()

    class Meta:
        model  = PredictionResult
        fields = [
            "id", "prediction_date", "model_version",
            "symptom_burden_score",
            "days_of_data", "data_completeness_pct",
            "status", "error_message",
            "infertility", "dysmenorrhea", "pmdd",
            "t2d", "cvd", "endometrial",
            "highest_risk",
            "created_at",
        ]
        read_only_fields = fields

    def _build_disease(self, score, flag, severity, risk_prob):
        return {
            "score":     score,
            "flag":      flag,
            "severity":  severity,
            "risk_prob": risk_prob,
            "message":   SEVERITY_MESSAGES.get(severity or "", SEVERITY_MESSAGES[""]),
        }

    def get_infertility(self, obj):
        return self._build_disease(obj.infertility_score, obj.infertility_flag,
                                   obj.infertility_severity, obj.infertility_risk_prob)

    def get_dysmenorrhea(self, obj):
        return self._build_disease(obj.dysmenorrhea_score, obj.dysmenorrhea_flag,
                                   obj.dysmenorrhea_severity, obj.dysmenorrhea_risk_prob)

    def get_pmdd(self, obj):
        return self._build_disease(obj.pmdd_score, obj.pmdd_flag,
                                   obj.pmdd_severity, obj.pmdd_risk_prob)

    def get_t2d(self, obj):
        return self._build_disease(obj.t2d_score, obj.t2d_flag,
                                   obj.t2d_severity, obj.t2d_risk_prob)

    def get_cvd(self, obj):
        return self._build_disease(obj.cvd_score, obj.cvd_flag,
                                   obj.cvd_severity, obj.cvd_risk_prob)

    def get_endometrial(self, obj):
        return self._build_disease(obj.endometrial_score, obj.endometrial_flag,
                                   obj.endometrial_severity, obj.endometrial_risk_prob)

    def get_highest_risk(self, obj):
        disease, severity = obj.get_highest_severity_disease()
        return {"disease": disease, "severity": severity,
                "message": SEVERITY_MESSAGES.get(severity, "")}

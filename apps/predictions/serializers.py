"""
apps/predictions/serializers.py
"""

from rest_framework import serializers
from .models import PredictionResult, PredictionSeverity, ComprehensivePredictionResult


class DiseaseResultSerializer(serializers.Serializer):
    score = serializers.FloatField()
    flag = serializers.BooleanField()
    severity = serializers.CharField()
    risk_prob = serializers.FloatField()
    message = serializers.CharField()


SEVERITY_MESSAGES = {
    "Minimal": "No significant clinical concern. Keep up your healthy habits.",
    "Mild": "Low-level signal detected. Monitor symptoms and maintain lifestyle changes.",
    "Moderate": "Elevated risk detected. A medical review is recommended.",
    "Severe": "High risk detected. Please consult a specialist soon.",
    "Extreme": "Critical risk level. Immediate clinical intervention is strongly advised.",
    "": "Insufficient data for assessment.",
}


class PredictionResultSerializer(serializers.ModelSerializer):
    # Flattened disease objects for frontend
    infertility = serializers.SerializerMethodField()
    dysmenorrhea = serializers.SerializerMethodField()
    pmdd = serializers.SerializerMethodField()
    t2d = serializers.SerializerMethodField()
    cvd = serializers.SerializerMethodField()
    endometrial = serializers.SerializerMethodField()
    highest_risk = serializers.SerializerMethodField()

    class Meta:
        model = PredictionResult
        fields = [
            "id",
            "prediction_date",
            "model_version",
            "symptom_burden_score",
            "days_of_data",
            "data_completeness_pct",
            "status",
            "error_message",
            "infertility",
            "dysmenorrhea",
            "pmdd",
            "t2d",
            "cvd",
            "endometrial",
            "highest_risk",
            "created_at",
        ]
        read_only_fields = fields

    def _build_disease(self, score, flag, severity, risk_prob):
        return {
            "score": score,
            "flag": flag,
            "severity": severity,
            "risk_prob": risk_prob,
            "message": SEVERITY_MESSAGES.get(severity or "", SEVERITY_MESSAGES[""]),
        }

    def get_infertility(self, obj):
        return self._build_disease(
            obj.infertility_score,
            obj.infertility_flag,
            obj.infertility_severity,
            obj.infertility_risk_prob,
        )

    def get_dysmenorrhea(self, obj):
        return self._build_disease(
            obj.dysmenorrhea_score,
            obj.dysmenorrhea_flag,
            obj.dysmenorrhea_severity,
            obj.dysmenorrhea_risk_prob,
        )

    def get_pmdd(self, obj):
        return self._build_disease(
            obj.pmdd_score, obj.pmdd_flag, obj.pmdd_severity, obj.pmdd_risk_prob
        )

    def get_t2d(self, obj):
        return self._build_disease(obj.t2d_score, obj.t2d_flag, obj.t2d_severity, obj.t2d_risk_prob)

    def get_cvd(self, obj):
        return self._build_disease(obj.cvd_score, obj.cvd_flag, obj.cvd_severity, obj.cvd_risk_prob)

    def get_endometrial(self, obj):
        return self._build_disease(
            obj.endometrial_score,
            obj.endometrial_flag,
            obj.endometrial_severity,
            obj.endometrial_risk_prob,
        )

    def get_highest_risk(self, obj):
        disease, severity = obj.get_highest_severity_disease()
        return {
            "disease": disease,
            "severity": severity,
            "message": SEVERITY_MESSAGES.get(severity, ""),
        }


class DiseasePredictionSerializer(serializers.Serializer):
    risk_score = serializers.FloatField()
    severity = serializers.CharField()
    risk_prob = serializers.FloatField(required=False, allow_null=True)
    risk_flag = serializers.IntegerField(required=False, allow_null=True)


class ComprehensivePredictionSerializer(serializers.ModelSerializer):
    """
    Serializer for ComprehensivePredictionResult.
    Includes all model predictions, severity flags, and data layer info.
    """

    all_predictions = serializers.SerializerMethodField()
    data_sources = serializers.SerializerMethodField()
    clinical_flags = serializers.SerializerMethodField()

    class Meta:
        model = ComprehensivePredictionResult
        fields = [
            "id",
            "final_risk_score",
            "risk_tier",
            "all_predictions",
            "data_layers_used",
            "data_completeness_pct",
            "data_sources",
            "severity_flags",
            "clinical_flags",
            "highest_risk_disease",
            "highest_risk_model",
            "patient_notified",
            "escalated_to_phc",
            "escalated_to_fmc",
            "computed_at",
        ]
        read_only_fields = fields

    def get_all_predictions(self, obj):
        """Combine all model predictions into one structure."""
        return {
            "symptom": obj.symptom_predictions or {},
            "menstrual": obj.menstrual_predictions or {},
            "rppg": obj.rppg_predictions or {},
            "mood": obj.mood_predictions or {},
        }

    def get_data_sources(self, obj):
        """Return formatted data source information."""
        sources = []
        layer_labels = {
            "symptom": {
                "name": "Symptom Check-ins",
                "description": "Daily check-in data",
                "icon": "📋",
            },
            "menstrual": {
                "name": "Menstrual Tracking",
                "description": "Cycle and period data",
                "icon": "🩺",
            },
            "rppg": {"name": "rPPG / HRV", "description": "Heart rate variability", "icon": "❤️"},
            "mood": {"name": "Mood Tracking", "description": "PHQ-4 and affect data", "icon": "🧠"},
        }

        for layer in obj.data_layers_used or []:
            info = layer_labels.get(layer, {"name": layer, "description": "", "icon": "📊"})
            sources.append(
                {
                    "layer": layer,
                    **info,
                    "active": True,
                }
            )

        return sources

    def get_clinical_flags(self, obj):
        """Return human-readable clinical interpretation."""
        flags = obj.severity_flags or {}
        interpretations = []

        if flags.get("ovulatory_dysfunction"):
            interpretations.append(
                {
                    "flag": "ovulatory_dysfunction",
                    "label": "Ovulatory Dysfunction",
                    "description": "Irregular or absent ovulation detected",
                    "severity": "warning",
                }
            )

        if flags.get("hyperandrogenism"):
            interpretations.append(
                {
                    "flag": "hyperandrogenism",
                    "label": "Hyperandrogenism",
                    "description": "Signs of elevated androgen levels",
                    "severity": "warning",
                }
            )

        if flags.get("metabolic_stress"):
            interpretations.append(
                {
                    "flag": "metabolic_stress",
                    "label": "Metabolic Stress",
                    "description": "Elevated metabolic stress indicators",
                    "severity": "warning",
                }
            )

        if flags.get("pcom_suspected"):
            interpretations.append(
                {
                    "flag": "pcom_suspected",
                    "label": "PCOM Suspected",
                    "description": "Multiple indicators suggest polycystic ovarian morphology",
                    "severity": "high",
                }
            )

        return interpretations

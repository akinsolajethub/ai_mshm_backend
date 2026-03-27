"""
apps/predictions/serializers.py
"""

from rest_framework import serializers
from .models import (
    PredictionResult,
    PredictionSeverity,
    ComprehensivePredictionResult,
    EnsembleWeightConfig,
)


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
    Now includes weighted ensemble scores, per-disease scores, and calculation breakdown.
    """

    all_predictions = serializers.SerializerMethodField()
    data_sources = serializers.SerializerMethodField()
    clinical_flags = serializers.SerializerMethodField()
    clinical_rules_applied = serializers.SerializerMethodField()
    calculation_explanation = serializers.SerializerMethodField()

    class Meta:
        model = ComprehensivePredictionResult
        fields = [
            "id",
            "final_risk_score",
            "risk_tier",
            "pcos_specific_score",
            "per_disease_scores",
            "all_predictions",
            "data_layers_used",
            "data_completeness_pct",
            "data_sources",
            "severity_flags",
            "clinical_flags",
            "clinical_rules_triggered",
            "clinical_rules_applied",
            "weights_used",
            "calculation_breakdown",
            "calculation_explanation",
            "highest_risk_disease",
            "highest_risk_model",
            "patient_notified",
            "escalated_to_phc",
            "escalated_to_fmc",
            "computed_at",
        ]
        read_only_fields = fields

    def get_clinical_rules_applied(self, obj):
        """Return formatted clinical rules that were triggered."""
        rules = obj.clinical_rules_triggered or []
        rule_labels = {
            "rotterdam_2_criteria_met": "Rotterdam 2 Criteria Met",
            "rotterdam_3_criteria_met": "Rotterdam 3 Criteria Met",
            "metabolic_reproductive_cluster": "Metabolic-Reproductive Cluster",
            "mood_rppg_stress_stack": "Mood-Stress Stack",
            "severe_amplification": "Severe Amplification",
        }
        return [
            {
                "rule": rule,
                "label": rule_labels.get(rule, rule.replace("_", " ").title()),
            }
            for rule in rules
        ]

    def get_calculation_explanation(self, obj):
        """Return human-readable explanation of how the score was calculated."""
        breakdown = obj.calculation_breakdown or {}
        explanation = []

        # Explain weighted ensemble
        explanation.append(
            "Your risk score is calculated using a weighted ensemble of 4 data sources: "
            "Symptom Check-ins (30%), Menstrual Tracking (25%), rPPG/HRV (25%), and Mood Tracking (20%)."
        )

        # Explain clinical rules
        rules = obj.clinical_rules_triggered or []
        if rules:
            explanation.append(
                f"Clinical rule adjustments were applied: {', '.join(r.title().replace('_', ' ') for r in rules)}."
            )

        # Explain data sources
        layers = obj.data_layers_used or []
        explanation.append(f"Analysis based on {len(layers)} data source(s): {', '.join(layers)}.")

        return " ".join(explanation)

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


class EnsembleWeightConfigSerializer(serializers.ModelSerializer):
    """
    Serializer for EnsembleWeightConfig.
    Allows admin to view and update ensemble weights per disease.
    """

    class Meta:
        model = EnsembleWeightConfig
        fields = [
            "id",
            "disease_name",
            "symptom_weight",
            "menstrual_weight",
            "rppg_weight",
            "mood_weight",
            "rotterdam_2_criteria_boost",
            "rotterdam_3_criteria_boost",
            "metabolic_reproductive_boost",
            "mood_rppg_stress_boost",
            "is_active",
            "updated_at",
        ]
        read_only_fields = ["id", "updated_at"]

    def validate(self, attrs):
        """Validate that weights sum to 1.0."""
        weights = [
            attrs.get("symptom_weight", 0.30),
            attrs.get("menstrual_weight", 0.25),
            attrs.get("rppg_weight", 0.25),
            attrs.get("mood_weight", 0.20),
        ]
        total = sum(weights)
        if abs(total - 1.0) > 0.001:
            raise serializers.ValidationError(
                {"non_field_errors": [f"Model weights must sum to 1.0 (current sum: {total:.3f})"]}
            )
        return attrs


class EnsembleWeightConfigListSerializer(serializers.Serializer):
    """Serializer for listing all weight configurations."""

    diseases = EnsembleWeightConfigSerializer(many=True)

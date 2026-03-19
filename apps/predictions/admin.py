from django.contrib import admin
from .models import PredictionResult


@admin.register(PredictionResult)
class PredictionResultAdmin(admin.ModelAdmin):
    list_display = (
        "user", "prediction_date", "model_version", "status",
        "infertility_severity", "dysmenorrhea_severity", "pmdd_severity",
        "t2d_severity", "cvd_severity", "endometrial_severity",
        "symptom_burden_score", "days_of_data", "patient_notified",
    )
    list_filter   = ("status", "model_version", "infertility_severity", "cvd_severity")
    search_fields = ("user__email",)
    date_hierarchy = "prediction_date"
    readonly_fields = (
        "id", "created_at", "updated_at",
        "feature_vector", "raw_daily_data",
        "symptom_burden_score",
        "infertility_score", "infertility_flag", "infertility_severity", "infertility_risk_prob",
        "dysmenorrhea_score", "dysmenorrhea_flag", "dysmenorrhea_severity", "dysmenorrhea_risk_prob",
        "pmdd_score", "pmdd_flag", "pmdd_severity", "pmdd_risk_prob",
        "t2d_score", "t2d_flag", "t2d_severity", "t2d_risk_prob",
        "cvd_score", "cvd_flag", "cvd_severity", "cvd_risk_prob",
        "endometrial_score", "endometrial_flag", "endometrial_severity", "endometrial_risk_prob",
    )
    fieldsets = (
        ("Patient & Date", {
            "fields": ("user", "prediction_date", "model_version", "status", "error_message"),
        }),
        ("Overall Burden", {
            "fields": ("symptom_burden_score", "days_of_data", "data_completeness_pct"),
        }),
        ("Disease Scores", {
            "fields": (
                "infertility_score", "infertility_flag", "infertility_severity", "infertility_risk_prob",
                "dysmenorrhea_score", "dysmenorrhea_flag", "dysmenorrhea_severity", "dysmenorrhea_risk_prob",
                "pmdd_score", "pmdd_flag", "pmdd_severity", "pmdd_risk_prob",
                "t2d_score", "t2d_flag", "t2d_severity", "t2d_risk_prob",
                "cvd_score", "cvd_flag", "cvd_severity", "cvd_risk_prob",
                "endometrial_score", "endometrial_flag", "endometrial_severity", "endometrial_risk_prob",
            ),
        }),
        ("Notifications", {
            "fields": ("patient_notified", "clinician_notified", "hcc_notified", "fhc_notified"),
        }),
        ("Audit", {
            "classes": ("collapse",),
            "fields": ("feature_vector", "raw_daily_data", "created_at", "updated_at"),
        }),
    )

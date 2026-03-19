"""
apps/predictions/views.py
══════════════════════════
GET  /api/v1/predictions/latest/          → most recent prediction
GET  /api/v1/predictions/history/         → paginated prediction history
GET  /api/v1/predictions/<id>/            → single prediction detail
GET  /api/v1/predictions/<id>/features/  → raw feature vector (for clinicians)
POST /api/v1/predictions/trigger/         → manually trigger prediction (admin/dev)
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from core.responses import success_response, error_response
from core.pagination import StandardResultsPagination
from core.permissions import IsPatient

from .models import PredictionResult
from .serializers import PredictionResultSerializer


class LatestPredictionView(APIView):
    permission_classes = [IsAuthenticated, IsPatient]

    @extend_schema(
        tags=["Predictions"],
        summary="Get latest prediction result",
        description=(
            "Returns the most recent ML prediction result for the authenticated patient. "
            "Each result contains scores, flags, severity, and risk probability for 6 conditions: "
            "Infertility, Dysmenorrhea, PMDD, Type 2 Diabetes, Cardiovascular Disease, and Endometrial Cancer. "
            "Returns null with a prompt message if fewer than 3 days of check-in data exist."
        ),
    )
    def get(self, request):
        result = PredictionResult.objects.filter(user=request.user).first()
        if not result:
            return success_response(data=None, message="No predictions yet. Complete check-ins for 3+ days.")
        return success_response(data=PredictionResultSerializer(result).data)


class PredictionHistoryView(APIView):
    permission_classes = [IsAuthenticated, IsPatient]

    @extend_schema(
        tags=["Predictions"],
        summary="Get prediction history",
        description="Returns paginated prediction results ordered by date descending. Each entry is a full prediction result.",
    )
    def get(self, request):
        qs = PredictionResult.objects.filter(user=request.user).order_by("-prediction_date")
        paginator = StandardResultsPagination()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(PredictionResultSerializer(page, many=True).data)


class PredictionDetailView(APIView):
    permission_classes = [IsAuthenticated, IsPatient]

    @extend_schema(
        tags=["Predictions"],
        summary="Get a single prediction result",
        description="Returns the full prediction result for a given prediction UUID.",
    )
    def get(self, request, pk):
        try:
            result = PredictionResult.objects.get(pk=pk, user=request.user)
        except PredictionResult.DoesNotExist:
            return error_response("Prediction not found.", http_status=404)
        return success_response(data=PredictionResultSerializer(result).data)


class PredictionFeaturesView(APIView):
    """For clinicians to audit the exact data used in a prediction."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Predictions"],
        summary="Get raw feature vector for a prediction (clinician audit)",
        description=(
            "Returns the exact 26-feature vector and raw 28-day daily data rows that were fed into "
            "the ML model for this prediction. Intended for clinician audit and explainability. "
            "Patients can only access their own predictions. Clinicians can access linked patients."
        ),
    )
    def get(self, request, pk):
        try:
            result = PredictionResult.objects.get(pk=pk)
        except PredictionResult.DoesNotExist:
            return error_response("Prediction not found.", http_status=404)

        # Patients can only see their own; clinicians can see linked patients
        if request.user.role == "patient" and result.user != request.user:
            return error_response("Not authorised.", http_status=403)

        return success_response(data={
            "feature_vector":        result.feature_vector,
            "days_of_data":          result.days_of_data,
            "data_completeness_pct": result.data_completeness_pct,
            "model_version":         result.model_version,
            "prediction_date":       str(result.prediction_date),
        })


class TriggerPredictionView(APIView):
    """
    POST /api/v1/predictions/trigger/
    Dev / admin endpoint to manually trigger inference for today.
    """
    permission_classes = [IsAuthenticated, IsPatient]

    @extend_schema(
        tags=["Predictions"],
        summary="Manually trigger prediction (dev/testing)",
        description=(
            "Forces a prediction run for today's summary regardless of completeness. "
            "Resets prediction_run flag and re-queues the ML pipeline. "
            "Use this during development to test predictions without waiting for both "
            "morning and evening sessions to complete."
        ),
    )
    def post(self, request):
        from django.utils import timezone
        from apps.health_checkin.models import DailyCheckinSummary
        from apps.health_checkin.services import DailySummaryService
        from .tasks import run_prediction_task

        today = timezone.localdate()
        summary, _ = DailyCheckinSummary.objects.get_or_create(
            user=request.user, summary_date=today
        )
        # Force re-run
        summary.prediction_run = False
        summary.save(update_fields=["prediction_run"])

        from core.utils.celery_helpers import run_task
        run_task(run_prediction_task, str(summary.id))
        return success_response(message="Prediction queued. Check /predictions/latest/ in a moment.")

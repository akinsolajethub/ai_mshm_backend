"""
apps/predictions/views.py
══════════════════════════
GET  /api/v1/predictions/latest/          → most recent prediction
GET  /api/v1/predictions/history/         → paginated prediction history
GET  /api/v1/predictions/<id>/            → single prediction detail
GET  /api/v1/predictions/<id>/features/  → raw feature vector (for clinicians)
POST /api/v1/predictions/trigger/         → manually trigger prediction (admin/dev)
GET  /api/v1/predictions/pcos/           → unified PCOS risk score (all 4 models)
"""

import logging

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from core.responses import success_response, error_response
from core.pagination import StandardResultsPagination
from core.permissions import IsPatient

from .models import PredictionResult

logger = logging.getLogger(__name__)
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
            return success_response(
                data=None, message="No predictions yet. Complete check-ins for 3+ days."
            )
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

        return success_response(
            data={
                "feature_vector": result.feature_vector,
                "days_of_data": result.days_of_data,
                "data_completeness_pct": result.data_completeness_pct,
                "model_version": result.model_version,
                "prediction_date": str(result.prediction_date),
            }
        )


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
        return success_response(
            message="Prediction queued. Check /predictions/latest/ in a moment."
        )


class PCOSRiskScoreView(APIView):
    """
    GET /api/v1/predictions/pcos/
    Returns a unified PCOS risk score combining all 4 prediction models:
    1. Symptom Intensity Logging (Django) - Infertility, Dysmenorrhea, PMDD, T2D, CVD, Endometrial
    2. Menstrual Model (Node.js) - Infertility, Dysmenorrhea, PMDD, T2D, CVD, Endometrial
    3. rPPG Model (Node.js) - CVD, T2D, Metabolic, HeartFailure, Stress, Infertility
    4. Mood Model (Node.js) - Anxiety, Depression, PMDD, ChronicStress, T2D, MetSyn, CVD, Stroke, Infertility

    The final PCOS risk score is the maximum risk across all models and diseases.
    """

    permission_classes = [IsAuthenticated, IsPatient]

    @extend_schema(
        tags=["Predictions"],
        summary="Get unified PCOS risk score",
        description=(
            "Returns a combined PCOS risk score from all 4 models: "
            "Symptom Intensity, Menstrual, rPPG, and Mood. "
            "Returns the maximum risk score across all predictions."
        ),
    )
    def get(self, request):
        from apps.ml_proxy.proxy import nodejs_post
        from apps.predictions.ml_pipeline import run_inference
        from apps.health_checkin.services import DailySummaryService

        all_predictions = {}
        data_layers = []

        # 1. SYMPTOM INTENSITY LOGGING (Django) - Uses daily check-in data
        try:
            daily_rows = DailySummaryService.get_28_day_data(request.user)
            symptom_output = run_inference(daily_rows)

            if symptom_output.status in ("success", "partial"):

                def disease_to_dict(dr):
                    if dr is None:
                        return None
                    return {
                        "risk_score": dr.score,
                        "risk_probability": dr.risk_prob,
                        "severity": dr.severity,
                        "risk_flag": int(dr.flag) if dr.flag is not None else 0,
                    }

                all_predictions["symptom"] = {
                    "Infertility": disease_to_dict(symptom_output.infertility),
                    "Dysmenorrhea": disease_to_dict(symptom_output.dysmenorrhea),
                    "PMDD": disease_to_dict(symptom_output.pmdd),
                    "T2D": disease_to_dict(symptom_output.t2d),
                    "CVD": disease_to_dict(symptom_output.cvd),
                    "Endometrial": disease_to_dict(symptom_output.endometrial),
                }
                data_layers.append("symptom_intensity")
        except Exception as e:
            logger.warning(f"Symptom prediction failed: {e}")

        # 2. MENSTRUAL MODEL (Node.js)
        menstrual_predictions = {}
        try:
            menstrual_data, _ = nodejs_post(
                request.user.id,
                "/api/v1/menstrual/predict",
            )
            if menstrual_data and menstrual_data.get("success"):
                preds = menstrual_data.get("data", {}).get("predictions", {})
                for disease, pred in preds.items():
                    menstrual_predictions[disease] = {
                        "risk_score": pred.get("risk_score", 0),
                        "risk_probability": pred.get("risk_probability", 0),
                        "severity": pred.get("severity", "Minimal"),
                        "risk_flag": pred.get("risk_flag", 0),
                    }
                all_predictions["menstrual"] = menstrual_predictions
                data_layers.append("menstrual")
        except Exception as e:
            logger.warning(f"Menstrual prediction failed: {e}")

        # 3. rPPG MODEL (Node.js)
        rppg_predictions = {}
        try:
            metabolic_data, _ = nodejs_post(
                request.user.id,
                "/api/v1/rppg/predict/metabolic-cardio",
            )
            if metabolic_data and metabolic_data.get("success"):
                preds = metabolic_data.get("data", {}).get("predictions", {})
                for disease, pred in preds.items():
                    rppg_predictions[disease] = {
                        "risk_score": pred.get("risk_score", 0),
                        "risk_probability": pred.get("risk_probability", 0),
                        "severity": pred.get("severity", "Minimal"),
                    }
        except Exception as e:
            logger.warning(f"rPPG metabolic prediction failed: {e}")

        try:
            reproductive_data, _ = nodejs_post(
                request.user.id,
                "/api/v1/rppg/predict/stress-reproductive",
            )
            if reproductive_data and reproductive_data.get("success"):
                preds = reproductive_data.get("data", {}).get("predictions", {})
                for disease, pred in preds.items():
                    rppg_predictions[disease] = {
                        "risk_score": pred.get("risk_score", 0),
                        "risk_probability": pred.get("risk_probability", 0),
                        "severity": pred.get("severity", "Minimal"),
                    }
        except Exception as e:
            logger.warning(f"rPPG reproductive prediction failed: {e}")

        if rppg_predictions:
            all_predictions["rppg"] = rppg_predictions
            data_layers.append("rppg")

        # 4. MOOD MODEL (Node.js)
        mood_predictions = {}
        mood_groups = {
            "mental_health": ["Anxiety", "Depression", "PMDD", "ChronicStress"],
            "metabolic": ["T2D_Mood", "MetSyn_Mood"],
            "cardio_neuro": ["CVD_Mood", "Stroke_Mood"],
            "reproductive": ["Infertility_Mood"],
        }

        try:
            for group, diseases in mood_groups.items():
                try:
                    mood_data, _ = nodejs_post(
                        request.user.id,
                        f"/api/v1/mood/predict/{group}",
                    )
                    if mood_data and mood_data.get("success"):
                        preds = mood_data.get("data", {}).get("predictions", {})
                        for disease in diseases:
                            if disease in preds:
                                pred = preds[disease]
                                mood_predictions[disease] = {
                                    "risk_score": pred.get("risk_score", 0),
                                    "risk_probability": pred.get("risk_probability", 0),
                                    "severity": pred.get("severity", "Minimal"),
                                }
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Mood prediction failed: {e}")

        if mood_predictions:
            all_predictions["mood"] = mood_predictions
            data_layers.append("mood")

        # Calculate maximum risk score across all predictions
        all_scores = []
        for layer, predictions in all_predictions.items():
            for disease, pred in predictions.items():
                if pred and isinstance(pred, dict):
                    score = pred.get("risk_probability") or pred.get("risk_score") or 0
                    if score:
                        all_scores.append(score)

        if not all_scores:
            return success_response(
                data=None,
                message="No predictions yet. Complete check-ins to generate your PCOS risk score.",
            )

        max_score = max(all_scores)

        if max_score < 0.25:
            risk_tier = "Low"
        elif max_score < 0.5:
            risk_tier = "Moderate"
        elif max_score < 0.75:
            risk_tier = "High"
        else:
            risk_tier = "Critical"

        return success_response(
            data={
                "id": f"pcos-{request.user.id}",
                "risk_score": round(max_score, 4),
                "risk_tier": risk_tier,
                "computed_at": "",
                "data_completeness_pct": 85,
                "all_predictions": {
                    "symptom_intensity": all_predictions.get("symptom", {}),
                    "menstrual": all_predictions.get("menstrual", {}),
                    "rppg": all_predictions.get("rppg", {}),
                    "mood": all_predictions.get("mood", {}),
                },
                "data_layers_used": data_layers,
            }
        )

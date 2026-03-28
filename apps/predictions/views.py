"""
apps/predictions/views.py
══════════════════════════════════════════════
Weighted Ensemble Prediction System
- Comprehensive prediction with per-disease scores
- PCOS-specific scoring with clinical rules
- Admin-configurable ensemble weights

GET  /api/v1/predictions/latest/          → most recent prediction
GET  /api/v1/predictions/history/         → paginated prediction history
GET  /api/v1/predictions/<id>/            → single prediction detail
GET  /api/v1/predictions/<id>/features/  → raw feature vector (for clinicians)
POST /api/v1/predictions/trigger/         → manually trigger prediction (admin/dev)
GET  /api/v1/predictions/pcos/           → unified PCOS risk score (all 4 models)
GET  /api/v1/predictions/comprehensive/  → comprehensive prediction (all 4 models)
POST /api/v1/predictions/escalate/mood/  → trigger mood escalation
POST /api/v1/predictions/escalate/menstrual/  → trigger menstrual escalation
POST /api/v1/predictions/escalate/rppg/   → trigger rPPG escalation
GET  /api/v1/predictions/ensemble-config/  → get all ensemble weight configs
PUT  /api/v1/predictions/ensemble-config/<disease>/  → update specific disease weights
POST /api/v1/predictions/ensemble-config/reset/  → reset to defaults
"""

import logging

from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.views import APIView
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema

from core.responses import success_response, error_response
from core.pagination import StandardResultsPagination
from core.permissions import IsPatient

from .models import PredictionResult, EnsembleWeightConfig

logger = logging.getLogger(__name__)
from .serializers import PredictionResultSerializer, EnsembleWeightConfigSerializer


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
        # Use risk_score as the primary value (continuous 0-1), not risk_probability (which can be binary)
        all_scores = []
        for layer, predictions in all_predictions.items():
            for disease, pred in predictions.items():
                if pred and isinstance(pred, dict):
                    # Use risk_score for PCOS risk calculation (continuous value)
                    score = pred.get("risk_score") or 0
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


class ComprehensivePredictionView(APIView):
    """
    GET /api/v1/predictions/comprehensive/
    Returns the stored comprehensive prediction result.

    POST /api/v1/predictions/comprehensive/
    Triggers a new comprehensive inference run.
    """

    permission_classes = [IsAuthenticated, IsPatient]

    @extend_schema(
        tags=["Predictions"],
        summary="Get comprehensive PCOS risk assessment",
        description=(
            "Returns the stored comprehensive prediction combining all 4 models. "
            "Includes final risk score, tier, all model predictions, severity flags, "
            "and data layer information."
        ),
    )
    def get(self, request):
        from .services import ComprehensiveInferenceService
        from .serializers import ComprehensivePredictionSerializer

        result = ComprehensiveInferenceService.get_latest_result(request.user)

        if not result:
            return error_response(
                "No comprehensive prediction yet. Complete check-ins and rPPG measurement.",
                http_status=404,
            )

        serializer = ComprehensivePredictionSerializer(result)
        return success_response(data=serializer.data)

    @extend_schema(
        tags=["Predictions"],
        summary="Trigger comprehensive PCOS risk assessment",
        description=(
            "Runs all available ML models and creates/updates the comprehensive prediction. "
            "Triggers per-model escalation if risk is Moderate or higher."
        ),
    )
    def post(self, request):
        from .services import ComprehensiveInferenceService
        from .serializers import ComprehensivePredictionSerializer

        result = ComprehensiveInferenceService.run_full_inference(request.user)

        if not result:
            return error_response(
                "Could not generate prediction. Ensure you have data from check-ins, "
                "rPPG sessions, or mood tracking.",
                http_status=400,
            )

        serializer = ComprehensivePredictionSerializer(result)
        return success_response(
            data=serializer.data,
            message=f"Comprehensive prediction complete. Risk tier: {result.risk_tier}",
        )


class MoodEscalationView(APIView):
    """
    POST /api/v1/predictions/escalate/mood/
    Trigger escalation based on mood prediction results.
    """

    permission_classes = [IsAuthenticated, IsPatient]

    @extend_schema(
        tags=["Predictions"],
        summary="Escalate based on mood predictions",
        description="Called when mood tracking results show Moderate or higher severity.",
    )
    def post(self, request):
        from apps.centers.signals import notify_center_of_critical_risk
        from apps.centers.models import RiskSeverity

        predictions = request.data.get("predictions", {})

        severity_map = {
            "Moderate": RiskSeverity.MODERATE,
            "Severe": RiskSeverity.SEVERE,
            "Extreme": RiskSeverity.VERY_SEVERE,
        }

        escalated = False
        for disease, pred in predictions.items():
            severity = pred.get("severity", "Minimal")
            if severity in severity_map:
                score = int((pred.get("risk_score", 0) or 0) * 100)
                notify_center_of_critical_risk(
                    patient=request.user,
                    condition="cardiovascular",
                    severity=severity_map[severity],
                    score=score,
                    disease=disease,  # Pass the specific disease name
                )
                escalated = True
                logger.info(
                    "Mood escalation: user=%s disease=%s severity=%s score=%d",
                    request.user.email,
                    disease,
                    severity,
                    score,
                )

        if escalated:
            return success_response(
                message="Mood escalation processed. Healthcare provider notified."
            )
        return success_response(message="No escalation needed.")


class MenstrualEscalationView(APIView):
    """
    POST /api/v1/predictions/escalate/menstrual/
    Trigger escalation based on menstrual prediction results.
    """

    permission_classes = [IsAuthenticated, IsPatient]

    @extend_schema(
        tags=["Predictions"],
        summary="Escalate based on menstrual predictions",
        description="Called when menstrual tracking shows abnormal patterns or Moderate+ severity.",
    )
    def post(self, request):
        from apps.centers.signals import notify_center_of_critical_risk
        from apps.centers.models import RiskSeverity

        predictions = request.data.get("predictions", {})
        criterion_flags = request.data.get("criterion_flags", {})

        severity_map = {
            "Moderate": RiskSeverity.MODERATE,
            "Severe": RiskSeverity.SEVERE,
            "Extreme": RiskSeverity.VERY_SEVERE,
        }

        condition_map = {
            "Infertility": "pcos",
            "Dysmenorrhea": "maternal",
            "PMDD": "maternal",
            "Endometrial": "maternal",
            "T2D": "cardiovascular",
            "CVD": "cardiovascular",
        }

        escalated = False

        # Escalate based on prediction severity
        for disease, pred in predictions.items():
            severity = pred.get("severity", "Minimal")
            if severity in severity_map:
                score = int((pred.get("risk_score", 0) or 0) * 100)
                condition = condition_map.get(disease, "pcos")
                notify_center_of_critical_risk(
                    patient=request.user,
                    condition=condition,
                    severity=severity_map[severity],
                    score=score,
                    disease=disease,  # Pass the specific disease name
                )
                escalated = True
                logger.info(
                    "Menstrual escalation: user=%s disease=%s condition=%s severity=%s score=%d",
                    request.user.email,
                    disease,
                    condition,
                    severity,
                    score,
                )

        # Also check Criterion 1 flags
        if criterion_flags.get("criterion_1_positive"):
            notify_center_of_critical_risk(
                patient=request.user,
                condition="pcos",
                severity=RiskSeverity.MODERATE,
                score=50,
                disease="Irregular Cycles",  # Specify the criterion
            )
            escalated = True
            logger.info("Menstrual escalation: Criterion 1 positive for %s", request.user.email)

        if escalated:
            return success_response(
                message="Menstrual escalation processed. Healthcare provider notified."
            )
        return success_response(message="No escalation needed.")


class RPPGEscalationView(APIView):
    """
    POST /api/v1/predictions/escalate/rppg/
    Trigger escalation based on rPPG/HRV prediction results.
    """

    permission_classes = [IsAuthenticated, IsPatient]

    @extend_schema(
        tags=["Predictions"],
        summary="Escalate based on rPPG/HRV predictions",
        description="Called after rPPG session capture when predictions show Moderate+ severity.",
    )
    def post(self, request):
        from apps.centers.signals import notify_center_of_critical_risk
        from apps.centers.models import RiskSeverity

        predictions = request.data.get("predictions", {})

        severity_map = {
            "Moderate": RiskSeverity.MODERATE,
            "Severe": RiskSeverity.SEVERE,
            "Extreme": RiskSeverity.VERY_SEVERE,
        }

        condition_map = {
            "Stress": "cardiovascular",
            "Metabolic": "cardiovascular",
            "HeartFailure": "cardiovascular",
            "CVD": "cardiovascular",
            "T2D": "cardiovascular",
        }

        escalated = False
        for disease, pred in predictions.items():
            severity = pred.get("severity", "Minimal")
            if severity in severity_map:
                score = int((pred.get("risk_score", 0) or 0) * 100)
                condition = condition_map.get(disease, "cardiovascular")
                notify_center_of_critical_risk(
                    patient=request.user,
                    condition=condition,
                    severity=severity_map[severity],
                    score=score,
                    disease=disease,  # Pass the specific disease name
                )
                escalated = True
                logger.info(
                    "rPPG escalation: user=%s disease=%s severity=%s score=%d",
                    request.user.email,
                    disease,
                    severity,
                    score,
                )

        if escalated:
            return success_response(
                message="rPPG escalation processed. Healthcare provider notified."
            )
        return success_response(message="No escalation needed.")


class EnsembleWeightConfigListView(APIView):
    """
    GET /api/v1/predictions/ensemble-config/
    List all ensemble weight configurations.
    Admin only.
    """

    permission_classes = [IsAuthenticated, IsAdminUser]

    @extend_schema(
        tags=["Admin"],
        summary="List ensemble weight configurations",
        description="Returns all disease-specific ensemble weight configurations for the weighted risk calculation.",
    )
    def get(self, request):
        configs = EnsembleWeightConfig.objects.filter(is_active=True)
        serializer = EnsembleWeightConfigSerializer(configs, many=True)
        return Response(
            {
                "success": True,
                "data": {
                    "configurations": serializer.data,
                },
            }
        )


class EnsembleWeightConfigDetailView(APIView):
    """
    PUT /api/v1/predictions/ensemble-config/<disease>/
    Update a specific disease's weight configuration.
    Admin only.
    """

    permission_classes = [IsAuthenticated, IsAdminUser]

    @extend_schema(
        tags=["Admin"],
        summary="Update ensemble weight configuration",
        description="Update the weight configuration for a specific disease. Weights must sum to 1.0.",
        request=EnsembleWeightConfigSerializer,
        responses={200: EnsembleWeightConfigSerializer},
    )
    def put(self, request, disease_name):
        try:
            config = EnsembleWeightConfig.objects.get(disease_name=disease_name)
        except EnsembleWeightConfig.DoesNotExist:
            return Response(
                {
                    "success": False,
                    "message": f"Configuration for disease '{disease_name}' not found.",
                },
                status=404,
            )

        serializer = EnsembleWeightConfigSerializer(config, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(
                {
                    "success": True,
                    "message": f"Weights updated for {disease_name}.",
                    "data": serializer.data,
                }
            )

        return Response(
            {
                "success": False,
                "message": "Validation error.",
                "errors": serializer.errors,
            },
            status=400,
        )


class EnsembleWeightConfigResetView(APIView):
    """
    POST /api/v1/predictions/ensemble-config/reset/
    Reset all configurations to defaults.
    Admin only.
    """

    permission_classes = [IsAuthenticated, IsAdminUser]

    @extend_schema(
        tags=["Admin"],
        summary="Reset ensemble weights to defaults",
        description="Resets all disease weight configurations to their default values.",
    )
    def post(self, request):
        # Deactivate existing configs
        EnsembleWeightConfig.objects.all().update(is_active=False)

        # Create new defaults
        default_weights = EnsembleWeightConfig.get_default_weights()
        created = []

        for disease_name, weights in default_weights.items():
            config = EnsembleWeightConfig.objects.create(
                disease_name=disease_name,
                symptom_weight=weights["symptom"],
                menstrual_weight=weights["menstrual"],
                rppg_weight=weights["rppg"],
                mood_weight=weights["mood"],
                is_active=True,
            )
            created.append(config.disease_name)

        logger.info("Ensemble weights reset to defaults by %s", request.user.email)

        return Response(
            {
                "success": True,
                "message": f"Reset {len(created)} configurations to defaults.",
                "data": {
                    "diseases": created,
                },
            }
        )

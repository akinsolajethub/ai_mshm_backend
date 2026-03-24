from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import serializers
from drf_spectacular.utils import extend_schema
from .proxy import nodejs_get, nodejs_post


class MenstrualLogCycleSerializer(serializers.Serializer):
    period_start_date = serializers.DateField()
    period_end_date = serializers.DateField()
    bleeding_scores = serializers.ListField(
        child=serializers.IntegerField(min_value=1, max_value=4),
        help_text="One integer per day: 1=Spotting 2=Light 3=Medium 4=Heavy",
    )
    has_ovulation_peak = serializers.BooleanField()
    unusual_bleeding = serializers.BooleanField()
    rppg_ovulation_day = serializers.IntegerField(allow_null=True, required=False)


class MoodLogPHQ4Serializer(serializers.Serializer):
    phq4_item1 = serializers.IntegerField(
        min_value=0, max_value=3, help_text="Nervous/anxious/on edge"
    )
    phq4_item2 = serializers.IntegerField(
        min_value=0, max_value=3, help_text="Cannot stop worrying"
    )
    phq4_item3 = serializers.IntegerField(
        min_value=0, max_value=3, help_text="Little interest or pleasure"
    )
    phq4_item4 = serializers.IntegerField(
        min_value=0, max_value=3, help_text="Feeling down/depressed"
    )
    log_date = serializers.DateField(required=False, help_text="YYYY-MM-DD, defaults to today")


class MoodLogAffectSerializer(serializers.Serializer):
    affect_valence = serializers.IntegerField(
        min_value=1, max_value=3, help_text="1=Negative 2=Neutral 3=Positive"
    )
    affect_arousal = serializers.IntegerField(
        min_value=1, max_value=3, help_text="1=Low 2=Medium 3=High"
    )
    affect_quadrant = serializers.CharField(required=False)
    log_date = serializers.DateField(required=False)


class MoodLogFocusSerializer(serializers.Serializer):
    cognitive_load_score = serializers.IntegerField(min_value=1, max_value=5)
    focus_score = serializers.IntegerField(min_value=1, max_value=10, required=False)
    memory_score = serializers.IntegerField(min_value=1, max_value=10, required=False)
    mental_fatigue = serializers.IntegerField(min_value=1, max_value=10, required=False)
    log_date = serializers.DateField(required=False)


class MoodLogSleepSerializer(serializers.Serializer):
    sleep_satisfaction = serializers.IntegerField(min_value=1, max_value=5)
    hours_slept = serializers.FloatField(required=False)
    log_date = serializers.DateField(required=False)


class MoodLogCompleteSerializer(serializers.Serializer):
    phq4_item1 = serializers.IntegerField(min_value=0, max_value=3)
    phq4_item2 = serializers.IntegerField(min_value=0, max_value=3)
    phq4_item3 = serializers.IntegerField(min_value=0, max_value=3)
    phq4_item4 = serializers.IntegerField(min_value=0, max_value=3)
    affect_valence = serializers.IntegerField(min_value=1, max_value=3)
    affect_arousal = serializers.IntegerField(min_value=1, max_value=3)
    affect_quadrant = serializers.CharField(required=False)
    cognitive_load_score = serializers.IntegerField(min_value=1, max_value=5)
    sleep_satisfaction = serializers.IntegerField(min_value=1, max_value=5)
    hours_slept = serializers.FloatField(required=False)
    cycle_phase = serializers.ChoiceField(
        choices=["Menstrual", "Follicular", "Ovulatory", "Luteal"], required=False
    )
    log_date = serializers.DateField(required=False)


# ─── MENSTRUAL CYCLE ENDPOINTS ──────────────────────────────────────────────


class MenstrualLogCycleView(APIView):
    """
    Log a completed menstrual cycle.
    Proxied to: POST /api/v1/menstrual/log-cycle on Node.js

    Call this at the END of each period (when user marks it finished).
    Required body:
    {
        "period_start_date": "YYYY-MM-DD",
        "period_end_date":   "YYYY-MM-DD",
        "bleeding_scores":   [2, 3, 3, 2, 1],
        "has_ovulation_peak": true,
        "unusual_bleeding":   false,
        "rppg_ovulation_day": null
    }
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Menstrual"],
        summary="Log a completed menstrual cycle",
        request=MenstrualLogCycleSerializer,
    )
    def post(self, request):
        data, status_code = nodejs_post(
            request.user.id,
            "/api/v1/menstrual/log-cycle",
            body=request.data,
        )
        return Response(data, status=status_code)


class MenstrualPredictView(APIView):
    """
    Run disease risk predictions from all stored menstrual cycles.
    Proxied to: POST /api/v1/menstrual/predict on Node.js

    No request body needed. The Node.js server reads stored cycles from its DB.
    Requires at least 1 logged cycle. Returns 6 disease risk scores:
    Infertility, Dysmenorrhea, PMDD, Endometrial Cancer, T2D, CVD.

    Call this immediately after a successful MenstrualLogCycleView response.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Menstrual"], summary="Run 6-disease menstrual risk prediction (no body needed)"
    )
    def post(self, request):
        data, status_code = nodejs_post(
            request.user.id,
            "/api/v1/menstrual/predict",
        )
        return Response(data, status=status_code)


class MenstrualHistoryView(APIView):
    """
    Get all stored menstrual cycles for the authenticated user.
    Proxied to: GET /api/v1/menstrual/history on Node.js

    Use this to populate the cycle history calendar/list screen.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Menstrual"], summary="Get all stored menstrual cycles")
    def get(self, request):
        data, status_code = nodejs_get(
            request.user.id,
            "/api/v1/menstrual/history",
        )
        return Response(data, status=status_code)


class MenstrualPredictionHistoryView(APIView):
    """
    Get the last 20 menstrual prediction results for risk trend charts.
    Proxied to: GET /api/v1/menstrual/predictions on Node.js

    Use this to populate the risk score trend chart on the dashboard.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Menstrual"], summary="Get last 20 menstrual prediction results for trend charts"
    )
    def get(self, request):
        data, status_code = nodejs_get(
            request.user.id,
            "/api/v1/menstrual/predictions",
        )
        return Response(data, status=status_code)


# ─── MOOD & COGNITIVE ENDPOINTS ─────────────────────────────────────────────


class MoodLogPHQ4View(APIView):
    """
    Log PHQ-4 mental wellness scores.
    Proxied to: POST /api/v1/mood/log/phq4 on Node.js

    Call after the user completes the PHQ-4 screen.
    Body:
    {
        "phq4_item1": 0-3,   (nervous/anxious/on edge)
        "phq4_item2": 0-3,   (can't stop worrying)
        "phq4_item3": 0-3,   (little interest/pleasure)
        "phq4_item4": 0-3,   (feeling down/depressed)
        "log_date":   "YYYY-MM-DD"   (optional, defaults to today)
    }
    Scale: 0=Not at all, 1=Several days, 2=More than half days, 3=Nearly every day
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Mood"], summary="Log PHQ-4 mental wellness scores", request=MoodLogPHQ4Serializer
    )
    def post(self, request):
        data, status_code = nodejs_post(
            request.user.id,
            "/api/v1/mood/log/phq4",
            body=request.data,
        )
        return Response(data, status=status_code)


class MoodLogAffectView(APIView):
    """
    Log Affect Grid (Arousal x Valence self-report).
    Proxied to: POST /api/v1/mood/log/affect on Node.js

    Call after the user completes the daily affect emoji grid.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Mood"],
        summary="Log Affect Grid — Arousal x Valence",
        request=MoodLogAffectSerializer,
    )
    def post(self, request):
        data, status_code = nodejs_post(
            request.user.id,
            "/api/v1/mood/log/affect",
            body=request.data,
        )
        return Response(data, status=status_code)


class MoodLogFocusView(APIView):
    """
    Log Cognitive Load / Focus & Memory score.
    Proxied to: POST /api/v1/mood/log/focus on Node.js

    Call after the user rates their focus and memory for the day.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Mood"], summary="Log Cognitive Load and Focus score", request=MoodLogFocusSerializer
    )
    def post(self, request):
        data, status_code = nodejs_post(
            request.user.id,
            "/api/v1/mood/log/focus",
            body=request.data,
        )
        return Response(data, status=status_code)


class MoodLogSleepView(APIView):
    """
    Log Sleep Quality / Satisfaction score.
    Proxied to: POST /api/v1/mood/log/sleep on Node.js

    Call after the morning check-in when user rates last night's sleep.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Mood"], summary="Log Sleep Quality and satisfaction", request=MoodLogSleepSerializer
    )
    def post(self, request):
        data, status_code = nodejs_post(
            request.user.id,
            "/api/v1/mood/log/sleep",
            body=request.data,
        )
        return Response(data, status=status_code)


class MoodLogCompleteView(APIView):
    """
    Log all 4 mood components (PHQ-4, Affect, Focus, Sleep) in a single call.
    Proxied to: POST /api/v1/mood/log/complete on Node.js

    Use this when the user finishes the full mood section of the check-in
    in one session. Preferred over calling the 4 individual endpoints separately.
    After this call succeeds, trigger MoodPredictView to refresh risk scores.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Mood"],
        summary="Log all 4 mood components in one call — preferred method",
        request=MoodLogCompleteSerializer,
    )
    def post(self, request):
        data, status_code = nodejs_post(
            request.user.id,
            "/api/v1/mood/log/complete",
            body=request.data,
        )
        return Response(data, status=status_code)


class MoodPredictView(APIView):
    """
    Get mood & cognitive disease risk scores (9 diseases).
    Proxied to: GET /api/v1/predict/mood-cognitive/predict on Node.js

    Returns risk scores for: Anxiety, Depression, PMDD, ChronicStress,
    CVD_Mood, T2D_Mood, Infertility_Mood, Stroke_Mood, MetSyn_Mood.

    Requires at least 3 days of mood log data in the Node.js database.
    Returns 400 with "insufficient_data" if fewer than 3 days exist.

    Call this after MoodLogCompleteView succeeds, or on dashboard load
    to retrieve the latest cached scores.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Mood"], summary="Get 9-disease mood and cognitive risk scores")
    def get(self, request):
        data, status_code = nodejs_get(
            request.user.id,
            "/api/v1/predict/mood-cognitive/predict",
        )
        return Response(data, status=status_code)


class MoodHistoryView(APIView):
    """
    Get mood log history for the authenticated user.
    Proxied to: GET /api/v1/mood/history on Node.js
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Mood"], summary="Get mood log history")
    def get(self, request):
        data, status_code = nodejs_get(
            request.user.id,
            "/api/v1/mood/history",
        )
        return Response(data, status=status_code)


class MoodPredictLatestView(APIView):
    """
    Get latest mood predictions.
    Proxied to: GET /api/v1/mood/predictions/latest on Node.js
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Mood"], summary="Get latest mood predictions")
    def get(self, request):
        data, status_code = nodejs_get(
            request.user.id,
            "/api/v1/mood/predictions/latest",
        )
        return Response(data, status=status_code)


class MoodPredictMentalHealthView(APIView):
    """POST /api/v1/mood/predict/mental-health — Proxied to Node.js"""

    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Mood"], summary="Predict mental health risks")
    def post(self, request):
        data, status_code = nodejs_post(
            request.user.id,
            "/api/v1/mood/predict/mental-health",
        )
        return Response(data, status=status_code)


class MoodPredictMetabolicView(APIView):
    """POST /api/v1/mood/predict/metabolic — Proxied to Node.js"""

    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Mood"], summary="Predict metabolic risks")
    def post(self, request):
        data, status_code = nodejs_post(
            request.user.id,
            "/api/v1/mood/predict/metabolic",
        )
        return Response(data, status=status_code)


class MoodPredictCardioNeuroView(APIView):
    """POST /api/v1/mood/predict/cardio-neuro — Proxied to Node.js"""

    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Mood"], summary="Predict cardiovascular and neurological risks")
    def post(self, request):
        data, status_code = nodejs_post(
            request.user.id,
            "/api/v1/mood/predict/cardio-neuro",
        )
        return Response(data, status=status_code)


class MoodPredictReproductiveView(APIView):
    """POST /api/v1/mood/predict/reproductive — Proxied to Node.js"""

    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Mood"], summary="Predict reproductive risks")
    def post(self, request):
        data, status_code = nodejs_post(
            request.user.id,
            "/api/v1/mood/predict/reproductive",
        )
        return Response(data, status=status_code)


# ─── MISSING MENSTRUAL ENDPOINTS ───────────────────────────────────────────────


class MenstrualPredictFromLogsView(APIView):
    """
    Predict disease risk from raw user-logged cycle data (stateless).
    Proxied to: POST /api/v1/menstrual/predict/from-logs on Node.js

    Accepts raw per-cycle logs as the user provides them in the app.
    Does NOT store cycles in the database — use POST /log-cycle for storage.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Menstrual"],
        summary="Predict disease risk from raw cycle data (stateless)",
    )
    def post(self, request):
        data, status_code = nodejs_post(
            request.user.id,
            "/api/v1/menstrual/predict/from-logs",
            body=request.data,
        )
        return Response(data, status=status_code)


class MenstrualFeaturesView(APIView):
    """
    Get feature schema and descriptions.
    Proxied to: GET /api/v1/menstrual/features on Node.js

    Returns the feature schema with descriptions for all 10 model input features.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Menstrual"], summary="Get feature schema and descriptions")
    def get(self, request):
        data, status_code = nodejs_get(
            request.user.id,
            "/api/v1/menstrual/features",
        )
        return Response(data, status=status_code)


class MenstrualModelInfoView(APIView):
    """
    Get model metadata, diseases, and metrics.
    Proxied to: GET /api/v1/menstrual/model-info on Node.js

    Returns model information including diseases, flag thresholds, severity bins, and model metrics.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Menstrual"], summary="Get model metadata, diseases, and metrics")
    def get(self, request):
        data, status_code = nodejs_get(
            request.user.id,
            "/api/v1/menstrual/model-info",
        )
        return Response(data, status=status_code)


# ─── rPPG (HRV) ENDPOINTS ───────────────────────────────────────────────────────


class RppgSessionSerializer(serializers.Serializer):
    rmssd = serializers.IntegerField(min_value=5, max_value=300, help_text="RMSSD in milliseconds (5–300)")
    mean_temp = serializers.FloatField(min_value=25, max_value=42, help_text="Mean skin temperature in °C (25–42)")
    mean_eda = serializers.FloatField(min_value=0, max_value=20, help_text="Mean electrodermal activity in µS (0–20)")
    asi = serializers.FloatField(min_value=0, max_value=2, allow_null=True, required=False, help_text="Autonomic Stress Index (0–1.58). Optional.")
    session_type = serializers.ChoiceField(choices=["morning", "evening", "baseline", "checkin"], default="checkin", help_text="Type of check-in session.")
    session_quality = serializers.ChoiceField(choices=["good", "poor", "motion_artifact"], allow_null=True, required=False, help_text="Signal quality flag from the device.")


class RppgSessionView(APIView):
    """
    Log an rPPG (HRV) session.
    Proxied to: POST /api/v1/rppg/session on Node.js

    Call this after the user completes an rPPG measurement session.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = RppgSessionSerializer

    @extend_schema(
        tags=["rPPG"],
        summary="Log an rPPG (HRV) session",
        request=RppgSessionSerializer,
    )
    def post(self, request):
        data, status_code = nodejs_post(
            request.user.id,
            "/api/v1/rppg/session",
            body=request.data,
        )
        return Response(data, status=status_code)


class RppgPredictMetabolicCardioView(APIView):
    """
    Predict metabolic and cardiovascular disease risks from rPPG data.
    Proxied to: POST /api/v1/rppg/predict/metabolic-cardio on Node.js

    Returns risk scores for: CVD, T2D, Metabolic, HeartFailure.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = serializers.Serializer  # No body needed for prediction

    @extend_schema(
        tags=["rPPG"],
        summary="Predict metabolic and cardiovascular disease risks from rPPG data",
    )
    def post(self, request):
        data, status_code = nodejs_post(
            request.user.id,
            "/api/v1/rppg/predict/metabolic-cardio",
        )
        return Response(data, status=status_code)


class RppgPredictStressReproductiveView(APIView):
    """
    Predict stress and reproductive disease risks from rPPG data.
    Proxied to: POST /api/v1/rppg/predict/stress-reproductive on Node.js

    Returns risk scores for: Stress, Infertility.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = serializers.Serializer  # No body needed for prediction

    @extend_schema(
        tags=["rPPG"],
        summary="Predict stress and reproductive disease risks from rPPG data",
    )
    def post(self, request):
        data, status_code = nodejs_post(
            request.user.id,
            "/api/v1/rppg/predict/stress-reproductive",
        )
        return Response(data, status=status_code)


class RppgPredictAnomalyView(APIView):
    """
    Run anomaly detection on rPPG data.
    Proxied to: POST /api/v1/rppg/predict/anomaly on Node.js

    Returns anomaly detection results for the rPPG session.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = serializers.Serializer  # No body needed for prediction

    @extend_schema(
        tags=["rPPG"],
        summary="Run anomaly detection on rPPG data",
    )
    def post(self, request):
        data, status_code = nodejs_post(
            request.user.id,
            "/api/v1/rppg/predict/anomaly",
        )
        return Response(data, status=status_code)


class RppgSessionsView(APIView):
    """
    Get rPPG session history for the authenticated user.
    Proxied to: GET /api/v1/rppg/sessions on Node.js

    Use this to populate the rPPG measurement history.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = serializers.Serializer  # GET endpoint, no body

    @extend_schema(tags=["rPPG"], summary="Get rPPG session history")
    def get(self, request):
        data, status_code = nodejs_get(
            request.user.id,
            "/api/v1/rppg/sessions",
        )
        return Response(data, status=status_code)


class RppgPredictionsView(APIView):
    """
    Get rPPG prediction history for the authenticated user.
    Proxied to: GET /api/v1/rppg/predictions on Node.js

    Use this to populate the rPPG prediction trend charts.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = serializers.Serializer  # GET endpoint, no body

    @extend_schema(tags=["rPPG"], summary="Get rPPG prediction history")
    def get(self, request):
        data, status_code = nodejs_get(
            request.user.id,
            "/api/v1/rppg/predictions",
        )
        return Response(data, status=status_code)

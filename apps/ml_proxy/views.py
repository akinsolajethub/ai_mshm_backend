from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .proxy import nodejs_get, nodejs_post


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

    def get(self, request):
        data, status_code = nodejs_get(
            request.user.id,
            "/api/v1/predict/mood-cognitive/predict",
        )
        return Response(data, status=status_code)

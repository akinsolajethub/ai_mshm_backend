"""
apps/health_checkin/views.py
══════════════════════════════
REST endpoints for all check-in screens.

Endpoint map:
  GET  /api/v1/checkin/today/                       → today's status for dashboard
  POST /api/v1/checkin/session/start/               → get_or_create session
  POST /api/v1/checkin/session/<uuid>/autosave/     → partial save mid-screen
  POST /api/v1/checkin/session/<uuid>/submit/       → mark complete + assemble summary
  POST/PATCH /api/v1/checkin/morning/<session_id>/  → morning data
  POST/PATCH /api/v1/checkin/evening/<session_id>/  → evening data
  POST /api/v1/checkin/hrv/                         → HRV capture result
  POST/PATCH /api/v1/checkin/mfg/                   → weekly hirsutism
  GET  /api/v1/checkin/history/                     → paginated daily summaries
  GET  /api/v1/checkin/summary/<date>/              → single day summary
"""
import logging
from datetime import date

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from core.responses import success_response, created_response, error_response
from core.pagination import StandardResultsPagination
from core.permissions import IsPatient

from .models import (
    CheckinSession, MorningCheckin, EveningCheckin, 
    HirsutismMFGCheckin, DailyCheckinSummary,
    SessionPeriod,
)
from .serializers import (
    CheckinSessionSerializer, MorningCheckinSerializer,
    EveningCheckinSerializer, HirsutismMFGSerializer, 
    DailyCheckinSummarySerializer, HRVSubmitSerializer, 
    TodayStatusSerializer,
)
from .services import (
    CheckinSessionService, DailySummaryService, MissedSessionService,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Today's status
# ─────────────────────────────────────────────────────────────────────────────

class TodayStatusView(APIView):
    """
    GET /api/v1/checkin/today/
    Dashboard calls this to know which sessions are done.
    Also surfaces missed-yesterday banners.
    """
    permission_classes = [IsAuthenticated, IsPatient]

    @extend_schema(
        tags=["Check-in"],
        summary="Get today's check-in status",
        description=(
            "Returns the current status of morning and evening sessions for today. "
            "Also returns missed-yesterday banners so the app can show a nudge. "
            "Call this on every dashboard open. Returns session IDs so the app knows "
            "which session to resume without calling /session/start/ again."
        ),
    )
    def get(self, request):
        status_data  = CheckinSessionService.get_today_status(request.user)
        missed_yday  = MissedSessionService.notify_yesterday_misses(request.user)
        status_data["missed_yesterday"] = missed_yday
        return success_response(data=status_data)


# ─────────────────────────────────────────────────────────────────────────────
# Session lifecycle
# ─────────────────────────────────────────────────────────────────────────────

class SessionStartView(APIView):
    """
    POST /api/v1/checkin/session/start/
    Body: { "period": "morning"|"evening", "checkin_date": "YYYY-MM-DD" (optional) }
    Mobile calls this on every screen open. Idempotent.
    """
    permission_classes = [IsAuthenticated, IsPatient]

    @extend_schema(
        tags=["Check-in"],
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "period": {"type": "string", "enum": ["morning", "evening"]},
                    "checkin_date": {"type": "string", "format": "date", "example": "2026-03-17"},
                },
                "required": ["period"],
            }
        },
        summary="Start or resume a check-in session",
        description=(
            "Idempotent — safe to call every time the morning or evening screen opens. "
            "Creates a new PENDING session if none exists, or returns the existing one. "
            "The returned session_id must be passed to all subsequent morning/, evening/, "
            "autosave/, submit/, and hrv/ calls. "
            "period must be 'morning' or 'evening'."
        ),
    )
    def post(self, request):
        period = request.data.get("period")
        if period not in [p.value for p in SessionPeriod]:
            return error_response("Invalid period. Must be morning, or evening.")

        date_str = request.data.get("checkin_date")
        checkin_date = date.fromisoformat(date_str) if date_str else timezone.localdate()

        session = CheckinSessionService.get_or_create_session(
            user=request.user, period=period, checkin_date=checkin_date,
        )
        return success_response(
            data=CheckinSessionSerializer(session).data,
            message=f"Session ready for {period}.",
        )


class SessionAutosaveView(APIView):
    """
    POST /api/v1/checkin/session/<session_id>/autosave/
    Called every time a slider changes on mobile.
    Just marks session as PARTIAL so data is not lost on app close.
    """
    permission_classes = [IsAuthenticated, IsPatient]

    @extend_schema(
        tags=["Check-in"],
        summary="Auto-save session progress",
        description=(
            "Marks the session as PARTIAL so data is not lost if the app closes mid-session. "
            "Call this every time any slider value changes on the morning or evening screen. "
            "Does not complete the session — use /session/<id>/submit/ for that."
        ),
    )
    def post(self, request, session_id):
        try:
            session = CheckinSession.objects.get(pk=session_id, user=request.user)
        except CheckinSession.DoesNotExist:
            return error_response("Session not found.", http_status=404)
        CheckinSessionService.save_partial(session)
        return success_response(message="Auto-saved.")


class SessionSubmitView(APIView):
    """
    POST /api/v1/checkin/session/<session_id>/submit/
    Marks the session as COMPLETE and assembles the daily summary.
    """
    permission_classes = [IsAuthenticated, IsPatient]

    @extend_schema(
        tags=["Check-in"],
        summary="Complete and submit a check-in session",
        description=(
            "Marks the session as COMPLETE and assembles the daily summary row. "
            "If both morning and evening are now complete for today, this automatically "
            "triggers the ML prediction pipeline. "
            "Returns the DailyCheckinSummary for the day."
        ),
    )
    def post(self, request, session_id):
        try:
            session = CheckinSession.objects.get(pk=session_id, user=request.user)
        except CheckinSession.DoesNotExist:
            return error_response("Session not found.", http_status=404)

        if session.status == "complete":
            return error_response("Session already completed.")

        summary = CheckinSessionService.complete_session(session)
        return success_response(
            data=DailyCheckinSummarySerializer(summary).data,
            message="Check-in complete. Thank you!",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Morning Check-in Data
# ─────────────────────────────────────────────────────────────────────────────

class MorningCheckinView(APIView):
    """
    POST   /api/v1/checkin/morning/<session_id>/  → create
    PATCH  /api/v1/checkin/morning/<session_id>/  → update (partial)
    GET    /api/v1/checkin/morning/<session_id>/  → retrieve
    """
    permission_classes = [IsAuthenticated, IsPatient]

    def _get_session(self, session_id, user):
        try:
            return CheckinSession.objects.get(pk=session_id, user=user, period=SessionPeriod.MORNING)
        except CheckinSession.DoesNotExist:
            return None

    @extend_schema(
        tags=["Check-in"],
        summary="Get saved morning check-in data",
        description="Returns previously saved fatigue, pelvic pressure, and PSQ-3 hyperalgesia values for this session.",
    )
    def get(self, request, session_id):
        session = self._get_session(session_id, request.user)
        if not session:
            return error_response("Session not found.", http_status=404)
        try:
            data = MorningCheckinSerializer(session.morning_data).data
        except MorningCheckin.DoesNotExist:
            data = None
        return success_response(data=data)

    @extend_schema(
        tags=["Check-in"],
        request=MorningCheckinSerializer,
        summary="Save morning check-in data",
        description=(
            "Saves fatigue VAS (0–10), pelvic pressure VAS (0–10), and the three PSQ-3 "
            "hyperalgesia sliders (skin sensitivity, muscle pressure pain, body tenderness — each 0–10). "
            "The hyperalgesia index is auto-computed as the mean of the three PSQ-3 values and stored "
            "as Painful_Touch_VAS for the ML model. Call /session/<id>/submit/ after this to complete."
        ),
    )
    def post(self, request, session_id):
        session = self._get_session(session_id, request.user)
        if not session:
            return error_response("Session not found.", http_status=404)

        try:
            instance = session.morning_data
            serializer = MorningCheckinSerializer(instance, data=request.data, partial=True)
        except MorningCheckin.DoesNotExist:
            serializer = MorningCheckinSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)
        obj = serializer.save(session=session)

        # Auto-save session state
        CheckinSessionService.save_partial(session)

        return success_response(
            data=MorningCheckinSerializer(obj).data,
            message="Morning data saved.",
        )

    @extend_schema(tags=["Check-in"], request=MorningCheckinSerializer,
                   summary="Partial update morning check-in")
    def patch(self, request, session_id):
        return self.post(request, session_id)


# ─────────────────────────────────────────────────────────────────────────────
# Evening Check-in Data
# ─────────────────────────────────────────────────────────────────────────────

class EveningCheckinView(APIView):
    permission_classes = [IsAuthenticated, IsPatient]

    def _get_session(self, session_id, user):
        try:
            return CheckinSession.objects.get(pk=session_id, user=user, period=SessionPeriod.EVENING)
        except CheckinSession.DoesNotExist:
            return None

    @extend_schema(
        tags=["Check-in"],
        summary="Get saved evening check-in data",
        description="Returns previously saved mastalgia, GAGS acne, bloating, and unusual bleeding values for this session.",
    )
    def get(self, request, session_id):
        session = self._get_session(session_id, request.user)
        if not session:
            return error_response("Session not found.", http_status=404)
        try:
            data = EveningCheckinSerializer(session.evening_data).data
        except EveningCheckin.DoesNotExist:
            data = None
        return success_response(data=data)

    @extend_schema(
        tags=["Check-in"],
        request=EveningCheckinSerializer,
        summary="Save evening check-in data",
        description=(
            "Saves cyclic mastalgia (left/right breast VAS 0–10, side, quality), "
            "GAGS acne scores per region (forehead, right cheek, left cheek, nose, chin, chest/back — each 0–4), "
            "bloating delta in cm, and unusual bleeding flag. "
            "GAGS total and mastalgia score are auto-computed. "
            "Breast_Soreness_VAS and Acne_Severity_Likert are normalised and stored for the ML model."
        ),
    )
    def post(self, request, session_id):
        session = self._get_session(session_id, request.user)
        if not session:
            return error_response("Session not found.", http_status=404)

        try:
            instance = session.evening_data
            serializer = EveningCheckinSerializer(instance, data=request.data, partial=True)
        except EveningCheckin.DoesNotExist:
            serializer = EveningCheckinSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)
        obj = serializer.save(session=session)
        CheckinSessionService.save_partial(session)
        return success_response(data=EveningCheckinSerializer(obj).data, message="Evening data saved.")

    @extend_schema(
        tags=["Check-in"],
        request=EveningCheckinSerializer,
        summary="Partial update evening check-in",
    )
    def patch(self, request, session_id):
        return self.post(request, session_id)


# ─────────────────────────────────────────────────────────────────────────────
# HRV Capture
# ─────────────────────────────────────────────────────────────────────────────

class HRVSubmitView(APIView):
    """
    POST /api/v1/checkin/hrv/
    Called after rPPG camera session completes (or is skipped).
    """
    permission_classes = [IsAuthenticated, IsPatient]

    @extend_schema(
        tags=["Check-in"],
        request=HRVSubmitSerializer,
        summary="Submit HRV result from rPPG camera session",
        description=(
            "Called after the 2-minute rPPG face scan completes on the HrvCaptureScreen. "
            "Saves SDNN and RMSSD in milliseconds to the session and propagates them to "
            "the daily summary. If the user tapped 'Skip for now', send skipped=true and "
            "omit the HRV values. Must include the session_id from the preceding morning or evening session."
        ),
    )
    def post(self, request):
        serializer = HRVSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        try:
            CheckinSessionService.submit_hrv(
                session_id=str(d["session_id"]),
                hrv_sdnn_ms=d.get("hrv_sdnn_ms"),
                hrv_rmssd_ms=d.get("hrv_rmssd_ms"),
                skipped=d.get("skipped", False),
            )
        except ValueError as e:
            return error_response(str(e), http_status=404)
        return success_response(message="HRV data recorded.")


# ─────────────────────────────────────────────────────────────────────────────
# Hirsutism mFG Weekly
# ─────────────────────────────────────────────────────────────────────────────

class HirsutismMFGView(APIView):
    """
    POST  /api/v1/checkin/mfg/          → submit weekly mFG assessment
    GET   /api/v1/checkin/mfg/          → latest mFG entry
    PATCH /api/v1/checkin/mfg/<date>/   → update a specific date's entry
    """
    permission_classes = [IsAuthenticated, IsPatient]

    @extend_schema(
        tags=["Check-in"],
        summary="Get latest mFG hirsutism score",
        description="Returns the most recently submitted Modified Ferriman-Gallwey assessment for this user.",
    )
    def get(self, request):
        latest = HirsutismMFGCheckin.objects.filter(user=request.user).first()
        if not latest:
            return success_response(data=None, message="No mFG assessment recorded yet.")
        return success_response(data=HirsutismMFGSerializer(latest).data)

    @extend_schema(
        tags=["Check-in"],
        request=HirsutismMFGSerializer,
        summary="Submit weekly mFG hirsutism assessment",
        description=(
            "Weekly assessment of hair growth across 9 body areas "
            "(upper lip, chin, chest, upper back, lower back, upper abdomen, lower abdomen, upper arm, thigh) "
            "each scored 0–4. Total mFG score (max 36) is auto-computed. "
            "Score feeds into Hirsutism_mFG_Score in the ML model. "
            "Interpretation: 0–7 Normal, 8–16 Mild, 17–24 Moderate, 25+ Severe."
        ),
    )
    def post(self, request):
        today = timezone.localdate()
        try:
            instance = HirsutismMFGCheckin.objects.get(user=request.user, assessed_date=today)
            serializer = HirsutismMFGSerializer(instance, data=request.data, partial=True)
        except HirsutismMFGCheckin.DoesNotExist:
            serializer = HirsutismMFGSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)
        obj = serializer.save(user=request.user, assessed_date=today)
        return created_response(
            data=HirsutismMFGSerializer(obj).data,
            message=f"mFG score saved: {obj.mfg_total_score}/36 — {obj.mfg_severity}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# History & Summary
# ─────────────────────────────────────────────────────────────────────────────

class CheckinHistoryView(APIView):
    """GET /api/v1/checkin/history/ — paginated daily summaries, newest first."""
    permission_classes = [IsAuthenticated, IsPatient]

    @extend_schema(
        tags=["Check-in"],
        summary="Get paginated check-in history",
        description="Returns daily summary rows newest-first. Each row represents one day's aggregated ML input.",
    )
    def get(self, request):
        qs = DailyCheckinSummary.objects.filter(
            user=request.user,
        ).order_by("-summary_date")
        paginator = StandardResultsPagination()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(DailyCheckinSummarySerializer(page, many=True).data)


class CheckinDaySummaryView(APIView):
    """GET /api/v1/checkin/summary/<date>/ — single day summary."""
    permission_classes = [IsAuthenticated, IsPatient]

    @extend_schema(
        tags=["Check-in"],
        summary="Get check-in summary for a specific date",
        description="Returns the assembled daily summary for a given date in YYYY-MM-DD format.",
    )
    def get(self, request, summary_date: str):
        try:
            d = date.fromisoformat(summary_date)
        except ValueError:
            return error_response("Invalid date format. Use YYYY-MM-DD.")
        try:
            summary = DailyCheckinSummary.objects.get(user=request.user, summary_date=d)
        except DailyCheckinSummary.DoesNotExist:
            return error_response(f"No summary found for {summary_date}.", http_status=404)
        return success_response(data=DailyCheckinSummarySerializer(summary).data)

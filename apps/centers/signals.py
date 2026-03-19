"""
apps/centers/signals.py
────────────────────────
Escalation notification routing. Creates PHCPatientRecord and PatientCase
automatically based on severity.

WHAT GETS CREATED:
  Mild/Moderate → PHCPatientRecord at patient's registered PHC
  Severe/Very Severe → PatientCase at PHC's linked FMC

FULL ROUTING:
  Patient → registered_hcc → PHCPatientRecord (mild/moderate)
  Patient → registered_hcc → get_escalation_fmc() → PatientCase (severe)
"""
import logging
from .models import RiskSeverity, PHCPatientRecord, PatientCase

logger = logging.getLogger(__name__)

_CONDITION_LABELS = {
    "pcos":           "PCOS",
    "maternal":       "Maternal Health",
    "cardiovascular": "Cardiovascular",
}
_SEVERITY_LABELS = dict(RiskSeverity.choices)

# Map string condition to model choice
_CONDITION_MAP = {
    "pcos":           PHCPatientRecord.Condition.PCOS,
    "maternal":       PHCPatientRecord.Condition.MATERNAL,
    "cardiovascular": PHCPatientRecord.Condition.CARDIOVASCULAR,
}


def notify_center_of_critical_risk(
    patient,
    condition: str,
    severity: str,
    score: int,
    previous_score: int = None,
) -> None:
    """
    Main entry point. Called by PredictionService._escalate().
    Routes notifications and creates records based on severity.
    """
    from apps.notifications.models import Notification
    from apps.notifications.services import NotificationService

    condition_label = _CONDITION_LABELS.get(condition, condition.title())
    severity_label  = _SEVERITY_LABELS.get(severity, severity)
    is_mild_or_mod  = severity in (RiskSeverity.MILD, RiskSeverity.MODERATE)
    is_very_severe  = severity == RiskSeverity.VERY_SEVERE

    base_data = {
        "patient_id":     str(patient.id),
        "patient_email":  patient.email,
        "patient_name":   patient.full_name,
        "condition":      condition,
        "severity":       severity,
        "score":          score,
        "previous_score": previous_score,
        "action":         "open_patient_risk_report",
    }

    # ── Step 1: Get patient's registered PHC ──────────────────────────────────
    hcc = _get_patient_phc(patient)

    if not hcc:
        _remind_patient_to_set_phc(patient, NotificationService, Notification)
        logger.warning(
            "No registered PHC for patient %s — skipping routing for %s %s",
            patient.email, condition, severity,
        )
        return

    # ── Step 2: Mild/Moderate → create PHCPatientRecord + notify PHC ─────────
    if is_mild_or_mod:
        record = _get_or_create_phc_record(
            patient=patient, hcc=hcc,
            condition=condition, severity=severity, score=score,
        )
        _notify_phc(
            hcc=hcc, patient=patient,
            condition_label=condition_label,
            severity_label=severity_label,
            score=score,
            base_data={**base_data, "record_id": str(record.id)},
            NotificationService=NotificationService,
            Notification=Notification,
        )
        return  # PHC only — FMC not involved

    # ── Step 3: Severe/Very Severe → find FMC + create PatientCase ───────────
    fmc = hcc.get_escalation_fmc()

    if not fmc:
        logger.warning(
            "PHC '%s' (state: %s) has no linked FMC. "
            "Cannot route FMC notification for patient %s — %s %s.",
            hcc.name, hcc.state, patient.email, condition, severity,
        )
        _get_or_create_case(patient=patient, fhc=None,
                            condition=condition, severity=severity, score=score)
        return

    case = _get_or_create_case(
        patient=patient, fhc=fmc,
        condition=condition, severity=severity, score=score,
    )
    case_data = {**base_data, "case_id": str(case.id), "fmc": fmc.name}

    # ── Step 4: Notify FMC admin ──────────────────────────────────────────────
    if fmc.admin_user:
        _send(
            NotificationService=NotificationService,
            recipient=fmc.admin_user,
            notification_type=Notification.NotificationType.RISK_UPDATE,
            title=(
                f"CRITICAL escalation: {severity_label} {condition_label}"
                if is_very_severe
                else f"Escalation: {severity_label} {condition_label}"
            ),
            body=(
                f"A patient (via {hcc.name}) has reached {severity_label} "
                f"{condition_label} risk ({score}/100). "
                + ("Immediate intervention required." if is_very_severe
                   else "Please assign a clinician.")
            ),
            priority=Notification.Priority.HIGH,
            data={**case_data, "critical": is_very_severe},
            log_label=f"FMC admin {fmc.admin_user.email}",
        )

    # ── Step 5: Notify all active FMC staff ───────────────────────────────────
    for staff_profile in fmc.get_active_staff():
        _send(
            NotificationService=NotificationService,
            recipient=staff_profile.user,
            notification_type=Notification.NotificationType.RISK_UPDATE,
            title=f"New case: {severity_label} {condition_label}",
            body=(
                f"Patient from {hcc.name} has {severity_label} {condition_label} "
                f"risk ({score}/100). Please assign a clinician."
            ),
            priority=Notification.Priority.HIGH,
            data=case_data,
            log_label=f"FMC staff {staff_profile.user.email}",
        )

    # ── Step 6: Notify assigned clinician if Very Severe ─────────────────────
    if is_very_severe and case.clinician:
        _send(
            NotificationService=NotificationService,
            recipient=case.clinician.user,
            notification_type=Notification.NotificationType.RISK_UPDATE,
            title=f"CRITICAL: Your patient reached {severity_label} {condition_label}",
            body=(
                f"{patient.full_name}'s {condition_label} risk escalated to "
                f"{severity_label} ({score}/100). Immediate review required."
            ),
            priority=Notification.Priority.HIGH,
            data={**case_data, "critical": True},
            log_label=f"clinician {case.clinician.user.email}",
        )


# ── PHC record helpers ────────────────────────────────────────────────────────

def _get_or_create_phc_record(
    patient, hcc, condition: str, severity: str, score: int,
) -> PHCPatientRecord:
    """
    Finds or creates a PHCPatientRecord for this patient + condition at this PHC.

    If an open record exists at the same PHC → update latest_score and severity.
    If an open record exists at a DIFFERENT PHC → patient changed PHC.
      Close the old record (DISCHARGED) and create new at current PHC.
    If no open record → create new.

    PHCPatientRecord does NOT block PHC changes — always creates fresh at new PHC.
    """
    case_condition = _CONDITION_MAP.get(condition, condition)

    existing = PHCPatientRecord.objects.filter(
        patient=patient,
        condition=case_condition,
        status__in=[
            PHCPatientRecord.RecordStatus.NEW,
            PHCPatientRecord.RecordStatus.UNDER_REVIEW,
            PHCPatientRecord.RecordStatus.ACTION_TAKEN,
        ],
    ).select_related("hcc").first()

    if existing:
        if existing.hcc_id == hcc.id:
            # Same PHC — update score and severity
            existing.latest_score = score
            existing.severity     = severity
            existing.save(update_fields=["latest_score", "severity"])
            return existing
        else:
            # Patient changed PHC — close old record, create new
            old_name = existing.hcc.name if existing.hcc else "unknown"
            existing.close(status=PHCPatientRecord.RecordStatus.DISCHARGED)
            logger.info(
                "Closed stale PHCPatientRecord at old PHC '%s' for patient %s. "
                "Creating new record at PHC '%s'.",
                old_name, patient.email, hcc.name,
            )

    # Create new record
    record = PHCPatientRecord.objects.create(
        patient=patient,
        hcc=hcc,
        condition=case_condition,
        severity=severity,
        status=PHCPatientRecord.RecordStatus.NEW,
        opening_score=score,
        latest_score=score,
    )
    logger.info(
        "PHCPatientRecord created: patient=%s condition=%s severity=%s hcc=%s",
        patient.email, condition, severity, hcc.name,
    )
    return record


# ── FMC case helpers ──────────────────────────────────────────────────────────

def _get_or_create_case(
    patient, fhc, condition: str, severity: str, score: int,
) -> PatientCase:
    """
    Finds or creates a PatientCase for this patient + condition at this FMC.

    SCENARIO 1 — No open case: create new.
    SCENARIO 2 — Open case, same FMC: reuse, update severity if worsening.
    SCENARIO 3 — Open OPEN case, FMC changed: close old, create new.
    SCENARIO 4 — Open ASSIGNED/UNDER_TREATMENT case, FMC changed: keep old.
    """
    # Reuse condition map from PHCPatientRecord
    case_condition_map = {
        "pcos":           PatientCase.Condition.PCOS,
        "maternal":       PatientCase.Condition.MATERNAL,
        "cardiovascular": PatientCase.Condition.CARDIOVASCULAR,
    }
    case_condition = case_condition_map.get(condition, condition)

    existing = PatientCase.objects.filter(
        patient=patient,
        condition=case_condition,
        status__in=[
            PatientCase.CaseStatus.OPEN,
            PatientCase.CaseStatus.ASSIGNED,
            PatientCase.CaseStatus.UNDER_TREATMENT,
        ],
    ).select_related("fhc", "clinician").first()

    if existing:
        new_fhc_id  = fhc.id if fhc else None
        fhc_changed = existing.fhc_id != new_fhc_id

        if fhc_changed:
            if existing.status == PatientCase.CaseStatus.OPEN:
                old_name = existing.fhc.name if existing.fhc else "none"
                existing.close(status=PatientCase.CaseStatus.DISCHARGED)
                logger.info(
                    "Closed stale OPEN PatientCase at old FMC '%s' for patient %s. "
                    "Creating new case at FMC '%s'.",
                    old_name, patient.email, fhc.name if fhc else "none",
                )
                # Fall through to create new
            else:
                # Clinician treating — do not disrupt
                logger.info(
                    "Patient %s changed PHC but case %s is %s at FMC '%s'. "
                    "Keeping existing case until discharged.",
                    patient.email, existing.id, existing.status,
                    existing.fhc.name if existing.fhc else "none",
                )
                return existing
        else:
            # Same FMC — update severity if worsening
            if (
                severity == RiskSeverity.VERY_SEVERE
                and existing.severity != RiskSeverity.VERY_SEVERE
            ):
                existing.severity = severity
                existing.save(update_fields=["severity"])
            return existing

    case = PatientCase.objects.create(
        patient=patient,
        fhc=fhc,
        condition=case_condition,
        severity=severity,
        status=PatientCase.CaseStatus.OPEN,
        opening_score=score,
    )
    logger.info(
        "PatientCase created: patient=%s condition=%s severity=%s fhc=%s",
        patient.email, condition, severity, fhc.name if fhc else "none",
    )
    return case


# ── Shared helpers ────────────────────────────────────────────────────────────

def _get_patient_phc(patient):
    try:
        hcc = patient.onboarding_profile.registered_hcc
        if hcc and hcc.status == "active":
            return hcc
        return None
    except Exception:
        return None


def _remind_patient_to_set_phc(patient, NotificationService, Notification):
    from django.utils import timezone
    from datetime import timedelta

    recent = patient.notifications.filter(
        notification_type=Notification.NotificationType.SYSTEM,
        data__action="set_phc_reminder",
        created_at__gte=timezone.now() - timedelta(days=7),
    ).exists()

    if recent:
        return

    _send(
        NotificationService=NotificationService,
        recipient=patient,
        notification_type=Notification.NotificationType.SYSTEM,
        title="Set your home health centre",
        body=(
            "Your health risk score was updated, but you haven't set a home "
            "Primary Health Centre yet. Add one in your profile settings."
        ),
        priority=Notification.Priority.MEDIUM,
        data={"action": "set_phc_reminder"},
        log_label=f"patient {patient.email} (no PHC reminder)",
    )


def _notify_phc(
    hcc, patient, condition_label, severity_label,
    score, base_data, NotificationService, Notification,
):
    """Notifies PHC admin and all active PHC staff for Mild/Moderate events."""
    if not hcc.notify_on_severe:
        logger.info("PHC '%s' notify_on_severe=False — skipping", hcc.name)
        return

    phc_data = {**base_data, "center": hcc.name, "center_type": "phc"}

    if hcc.admin_user:
        _send(
            NotificationService=NotificationService,
            recipient=hcc.admin_user,
            notification_type=Notification.NotificationType.RISK_UPDATE,
            title=f"Patient alert: {severity_label} {condition_label}",
            body=(
                f"Registered patient {patient.full_name} has {severity_label} "
                f"{condition_label} risk ({score}/100). Review recommended."
            ),
            priority=Notification.Priority.MEDIUM,
            data=phc_data,
            log_label=f"PHC admin {hcc.admin_user.email}",
        )

    for staff_profile in hcc.get_active_staff():
        _send(
            NotificationService=NotificationService,
            recipient=staff_profile.user,
            notification_type=Notification.NotificationType.RISK_UPDATE,
            title=f"Patient alert: {severity_label} {condition_label}",
            body=(
                f"{patient.full_name} has {severity_label} {condition_label} "
                f"risk ({score}/100). Consider scheduling a review."
            ),
            priority=Notification.Priority.MEDIUM,
            data=phc_data,
            log_label=f"PHC staff {staff_profile.user.email}",
        )


def _send(
    NotificationService, recipient, notification_type,
    title, body, priority, data, log_label,
):
    try:
        NotificationService.send(
            recipient=recipient,
            notification_type=notification_type,
            title=title, body=body, priority=priority, data=data,
        )
        logger.info("Notification sent to %s", log_label)
    except Exception as e:
        logger.error("Failed to notify %s: %s", log_label, e)
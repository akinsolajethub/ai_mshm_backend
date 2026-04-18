"""
apps/accounts/id_generator.py
─────────────────────────────
ID generator utility for user unique IDs.
Format: {PREFIX}/{YEAR}/{6-digit Sequential Number}
Example: MDC/2024/001234, PHC/2024/000001, FMC/2024/000001
"""

from django.utils import timezone
from django.contrib.auth import get_user_model
import threading

User = get_user_model()

_lock = threading.Lock()


def generate_unique_id(role: str) -> str:
    """
    Generate a unique ID based on user role.

    ID Prefixes by Role:
        # Direct to Consumer (Patients)
        PATIENT         → MDC (Medical Card)

        # Government & Public Health
        HCC_STAFF       → PHC (Primary Health Centre)
        HCC_ADMIN       → PHC
        STH_STAFF       → STH (State Hospital)
        STH_ADMIN       → STH
        STTH_STAFF      → STTH (State Teaching Hospital)
        STTH_ADMIN      → STTH
        FHC_STAFF       → FMC (Federal Medical Centre)
        FHC_ADMIN       → FMC
        FTH_STAFF       → FTH (Federal Teaching Hospital)
        FTH_ADMIN       → FTH
        CLINICIAN       → CLN (Clinician - assigned to any hospital)

        # Health Insurance & HMOs
        HMO_STAFF       → HMO
        HMO_ADMIN       → HMO

        # Private Healthcare
        CLINIC_STAFF    → CLN (Clinic)
        CLINIC_ADMIN    → CLN
        PVT_STAFF       → PVT (Private Hospital)
        PVT_ADMIN       → PVT
        PTTH_STAFF      → PTTH (Private Teaching Hospital)
        PTTH_ADMIN      → PTTH

        # Platform Admin
        ADMIN           → ADT

    Format: {PREFIX}/{YEAR}/{6-digit Sequential}
    Example: MDC/2024/001234, PHC/2024/000001, STH/2024/000001
    """
    prefix_map = {
        # Direct to Consumer
        "patient": "MDC",
        # Government & Public Health
        "hcc_staff": "PHC",
        "hcc_admin": "PHC",
        "sth_staff": "STH",
        "sth_admin": "STH",
        "stth_staff": "STTH",
        "stth_admin": "STTH",
        "fhc_staff": "FMC",
        "fhc_admin": "FMC",
        "fth_staff": "FTH",
        "fth_admin": "FTH",
        "clinician": "CLN",
        # Health Insurance & HMOs
        "hmo_staff": "HMO",
        "hmo_admin": "HMO",
        # Private Healthcare
        "clinic_staff": "CLN",
        "clinic_admin": "CLN",
        "pvt_staff": "PVT",
        "pvt_admin": "PVT",
        "ptth_staff": "PTTH",
        "ptth_admin": "PTTH",
        # Platform Admin
        "admin": "ADT",
    }

    prefix = prefix_map.get(role.lower(), "UKN")
    year = timezone.now().year
    sequence = _get_next_sequence(prefix, year)

    return f"{prefix}/{year}/{sequence:06d}"


def _get_next_sequence(prefix: str, year: int) -> int:
    """
    Get the next sequence number for a given prefix and year.
    Uses thread-safe locking to handle concurrent requests.
    """
    with _lock:
        key = f"{prefix}_{year}"

        last_id = (
            User.objects.filter(unique_id__startswith=f"{prefix}/{year}/")
            .order_by("-unique_id")
            .values_list("unique_id", flat=True)
            .first()
        )

        if last_id:
            try:
                last_seq = int(last_id.split("/")[-1])
                return last_seq + 1
            except (ValueError, IndexError):
                pass

        return 1


def generate_id_for_user(user: User) -> str:
    """
    Generate and assign a unique ID to a user instance.
    """
    unique_id = generate_unique_id(user.role)
    user.unique_id = unique_id
    user.save(update_fields=["unique_id"])
    return unique_id

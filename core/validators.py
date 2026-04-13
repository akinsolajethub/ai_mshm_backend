"""
core/validators.py
───────────────────
Reusable serializer / model field validators for input sanitization and validation.

Usage:
    from core.validators import validate_phone_number, validate_future_date, sanitize_html, validate_uuid

    class MySerializer(serializers.Serializer):
        phone = serializers.CharField(validators=[validate_phone_number])
"""

import re
import uuid
from datetime import date
from html import escape as html_escape

from django.core.exceptions import ValidationError
from rest_framework import serializers
from django.utils import timezone


# ───────────────────────────────────────────────────────────────────────────────────────────
# CORE INPUT SANITIZATION
# ───────────────────────────────────────────────────────────────────────────────────────────


def sanitize_string(value: str, max_length: int = None) -> str:
    """
    Sanitize a string input - remove dangerous characters and control sequences.
    """
    if not value:
        return value

    # Remove null bytes and control characters (except newlines/tabs)
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)

    # Strip leading/trailing whitespace
    value = value.strip()

    if max_length:
        value = value[:max_length]

    return value


def sanitize_html(value: str) -> str:
    """
    Safely escape HTML to prevent XSS attacks.
    Use for any field that will be rendered in HTML.
    """
    if not value:
        return value
    return html_escape(value)


def sanitize_email(value: str) -> str:
    """
    Sanitize and validate email input.
    """
    if not value:
        return value

    # Lowercase, strip whitespace
    value = value.lower().strip()

    # Remove any null bytes
    value = value.replace("\x00", "")

    # Basic email regex (RFC 5322 simplified)
    if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", value):
        raise ValidationError("Invalid email address format.")

    return value


def sanitize_search_query(value: str, max_length: int = 200) -> str:
    """
    Sanitize search query to prevent injection attacks.
    Strips special characters that could be used for injection.
    """
    if not value:
        return value

    value = value.strip()[:max_length]

    # Remove characters that could be used for injection
    value = re.sub(r"[;\'\"\\`|<>${}()\[\]]", "", value)

    return value


# ───────────────────────────────────────────────────────────────────────────────────────────
# UUID VALIDATION
# ───────────────────────────────────────────────────────────────────────────────────────────


def validate_uuid(value: str) -> uuid.UUID:
    """
    Validate UUID format - prevents path traversal and invalid IDs.
    """
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError):
        raise ValidationError("Invalid UUID format.")


def validate_uuid_list(value: list) -> list:
    """
    Validate list of UUIDs.
    """
    for item in value:
        validate_uuid(str(item))
    return value


# ───────────────────────────────────────────────────────────────────────────────────────────
# NUMERIC VALIDATION
# ───────────────────────────────────────────────────────────────────────────────────────────


def validate_positive_int(value) -> int:
    """Validate positive integer."""
    try:
        value = int(value)
        if value < 0:
            raise ValidationError("Value must be positive.")
        return value
    except (ValueError, TypeError):
        raise ValidationError("Value must be a valid integer.")


def validate_range(value, min_val: float, max_val: float) -> float:
    """Validate value is within range."""
    try:
        value = float(value)
        if not (min_val <= value <= max_val):
            raise ValidationError(f"Value must be between {min_val} and {max_val}.")
        return value
    except (ValueError, TypeError):
        raise ValidationError("Value must be a valid number.")


# ───────────────────────────────────────────────────────────────────────────────────────────
# CHOICE VALIDATION
# ───────────────────────────────────────────────────────────────────────────────────────────


def validate_choice(value, choices: list, field_name: str = "Value"):
    """Validate value is in allowed choices."""
    if value not in choices:
        raise ValidationError(f"{field_name} must be one of: {', '.join(choices)}.")
    return value


def validate_stripped_choice(value, choices: list, field_name: str = "Value") -> str:
    """Validate choice after stripping whitespace."""
    value = value.strip()
    validate_choice(value, choices, field_name)
    return value


# ────────────────────────────────────��──────────────────────────────────────────────────────
# PHONE & DATE VALIDATION
# ───────────────────────────────────────────────────────────────────────────────────────────


def validate_phone_number(value: str) -> str:
    """E.164 format: +2348012345678"""
    pattern = re.compile(r"^\+[1-9]\d{7,14}$")
    if not pattern.match(value):
        raise ValidationError("Enter a valid phone number in E.164 format (e.g. +2348012345678).")
    return value


def validate_future_date(value: date) -> date:
    if value <= timezone.now().date():
        raise ValidationError("Date must be in the future.")
    return value


def validate_past_date(value: date) -> date:
    if value > timezone.now().date():
        raise ValidationError("Date cannot be in the future.")
    return value


def validate_positive_number(value) -> float:
    if value is not None and value <= 0:
        raise ValidationError("Value must be a positive number.")
    return value


def validate_percentage(value) -> int:
    if not (0 <= value <= 100):
        raise ValidationError("Value must be between 0 and 100.")
    return value


def validate_vas_score(value) -> int:
    """Visual Analogue Scale: 0–10"""
    if not (0 <= value <= 10):
        raise ValidationError("VAS score must be between 0 and 10.")
    return value


def validate_time_hhmm(value: str) -> str:
    """Validates HH:MM format."""
    if not re.match(r"^\d{2}:\d{2}$", value):
        raise ValidationError("Time must be in HH:MM format.")
    h, m = map(int, value.split(":"))
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValidationError("Invalid time: hours must be 0–23, minutes 0–59.")
    return value


def validate_image(value, max_mb: int = 5):
    """
    Validates an uploaded image file.
    Use in any serializer that accepts image uploads (avatar, rPPG, reports, etc.)

    Usage:
        def validate_avatar(self, value):
            return validate_image(value, max_mb=5)
        Validates image size only — Django's ImageField already rejects
        non-images (SVG, corrupted files) before this runs.
    """
    if value is None:
        return value

    if value.size > max_mb * 1024 * 1024:
        raise serializers.ValidationError(f"Image must be under {max_mb}MB.")

    return value


def validate_document(value, max_mb: int = 10):
    """
    Validates an uploaded document file.
    Use for reports, exports, PDFs, etc.

    Usage:
        def validate_report(self, value):
            return validate_document(value, max_mb=10)
    """
    if value is None:
        return value

    if value.size > max_mb * 1024 * 1024:
        raise serializers.ValidationError(f"Document must be under {max_mb}MB.")

    allowed_types = [
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ]
    if value.content_type not in allowed_types:
        raise serializers.ValidationError(
            "Unsupported file format. Please upload a PDF or Word document."
        )
    return value


def validate_video(value, max_mb: int = 50):
    """
    Validates an uploaded video file.
    Use for rPPG signal uploads when the pipeline is ready.

    Usage:
        def validate_signal_video(self, value):
            return validate_video(value, max_mb=50)
    """
    if value is None:
        return value

    if value.size > max_mb * 1024 * 1024:
        raise serializers.ValidationError(f"Video must be under {max_mb}MB.")

    allowed_types = ["video/mp4", "video/quicktime", "video/webm"]
    if value.content_type not in allowed_types:
        raise serializers.ValidationError(
            "Unsupported video format. Please upload an MP4, MOV, or WebM file."
        )
    return value

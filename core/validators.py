"""
core/validators.py
───────────────────
Reusable serializer / model field validators.

Usage:
    from core.validators import validate_phone_number, validate_future_date

    class MySerializer(serializers.Serializer):
        phone = serializers.CharField(validators=[validate_phone_number])
"""
import re
from datetime import date

from django.core.exceptions import ValidationError
from rest_framework import serializers
from django.utils import timezone


def validate_phone_number(value: str) -> str:
    """E.164 format: +2348012345678"""
    pattern = re.compile(r"^\+[1-9]\d{7,14}$")
    if not pattern.match(value):
        raise ValidationError(
            "Enter a valid phone number in E.164 format (e.g. +2348012345678)."
        )
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
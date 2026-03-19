"""
core/exceptions/handlers.py
────────────────────────────
Overrides DRF's default exception handler to return our standardised envelope.
Also catches ServiceException subclasses raised from service layer.
"""
import logging

from django.core.exceptions import PermissionDenied
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    NotAuthenticated,
    ValidationError,
)
from rest_framework.response import Response
from rest_framework.views import exception_handler

from core.exceptions import ServiceException

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    """
    Returns JSON in the shape:
        { "status": "error", "message": "...", "data": null, "errors": {...} }
    """
    # Handle our own ServiceException hierarchy directly
    if isinstance(exc, ServiceException):
        return Response(
            {
                "status": "error",
                "message": str(exc.detail) if hasattr(exc, "detail") else str(exc),
                "data": None,
                "errors": None,
            },
            status=exc.status_code,
        )

    # Let DRF produce its standard Response first
    response = exception_handler(exc, context)

    if response is None:
        logger.exception("Unhandled exception in %s: %s", context.get("view"), exc)
        return None

    # Map common exceptions to friendly messages
    if isinstance(exc, (NotAuthenticated, AuthenticationFailed)):
        message = "Authentication credentials were not provided or are invalid."
        http_status = status.HTTP_401_UNAUTHORIZED
        errors = None
    elif isinstance(exc, PermissionDenied):
        message = "You do not have permission to perform this action."
        http_status = status.HTTP_403_FORBIDDEN
        errors = None
    elif isinstance(exc, Http404):
        message = "The requested resource was not found."
        http_status = status.HTTP_404_NOT_FOUND
        errors = None
    elif isinstance(exc, ValidationError):
        message = "Validation failed. Please check the provided data."
        http_status = response.status_code
        errors = response.data
    else:
        message = str(getattr(exc, "detail", exc))
        http_status = response.status_code
        errors = None

    response.data = {
        "status": "error",
        "message": message,
        "data": None,
        "errors": errors,
    }
    response.status_code = http_status
    return response

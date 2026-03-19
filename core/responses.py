"""
core/responses.py
──────────────────
Centralised response builders so every endpoint returns a consistent envelope:

    {
        "status": "success" | "error",
        "message": "...",
        "data": {...} | [...] | null,
        "errors": {...} | null,     # only on error
        "meta": {...}               # optional (pagination, etc.)
    }
"""
from rest_framework.response import Response
from rest_framework import status


def success_response(
    data=None,
    message: str = "Request successful",
    http_status: int = status.HTTP_200_OK,
    meta: dict | None = None,
) -> Response:
    payload: dict = {"status": "success", "message": message, "data": data}
    if meta:
        payload["meta"] = meta
    return Response(payload, status=http_status)


def created_response(
    data=None,
    message: str = "Resource created successfully",
    meta: dict | None = None,
) -> Response:
    return success_response(data=data, message=message, http_status=status.HTTP_201_CREATED, meta=meta)


def error_response(
    message: str = "An error occurred",
    errors=None,
    http_status: int = status.HTTP_400_BAD_REQUEST,
) -> Response:
    payload: dict = {"status": "error", "message": message, "data": None}
    if errors:
        payload["errors"] = errors
    return Response(payload, status=http_status)

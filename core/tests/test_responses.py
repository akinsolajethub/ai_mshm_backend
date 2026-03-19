"""
core/tests/test_responses.py
──────────────────────────────
Tests for standardised response helpers.
"""
import pytest
from rest_framework import status

from core.responses import success_response, created_response, error_response


class TestSuccessResponse:
    def test_status_field(self):
        resp = success_response()
        assert resp.data["status"] == "success"

    def test_default_message(self):
        resp = success_response()
        assert resp.data["message"] == "Request successful"

    def test_custom_message(self):
        resp = success_response(message="Done!")
        assert resp.data["message"] == "Done!"

    def test_data_included(self):
        resp = success_response(data={"key": "value"})
        assert resp.data["data"] == {"key": "value"}

    def test_default_http_200(self):
        resp = success_response()
        assert resp.status_code == status.HTTP_200_OK

    def test_custom_http_status(self):
        resp = success_response(http_status=status.HTTP_202_ACCEPTED)
        assert resp.status_code == status.HTTP_202_ACCEPTED

    def test_meta_included_when_provided(self):
        resp = success_response(meta={"count": 5, "next": None})
        assert resp.data["meta"]["count"] == 5

    def test_no_meta_when_not_provided(self):
        resp = success_response()
        assert "meta" not in resp.data


class TestCreatedResponse:
    def test_http_201(self):
        resp = created_response()
        assert resp.status_code == status.HTTP_201_CREATED

    def test_default_message(self):
        resp = created_response()
        assert "created" in resp.data["message"].lower()

    def test_status_success(self):
        resp = created_response(data={"id": 1})
        assert resp.data["status"] == "success"
        assert resp.data["data"]["id"] == 1


class TestErrorResponse:
    def test_status_field(self):
        resp = error_response("Something went wrong")
        assert resp.data["status"] == "error"

    def test_message_included(self):
        resp = error_response("Bad input")
        assert resp.data["message"] == "Bad input"

    def test_data_is_null(self):
        resp = error_response("Error")
        assert resp.data["data"] is None

    def test_default_http_400(self):
        resp = error_response("Error")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_custom_http_status(self):
        resp = error_response("Not found", http_status=status.HTTP_404_NOT_FOUND)
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_errors_dict_included(self):
        errors = {"email": ["Invalid email."]}
        resp = error_response("Validation failed", errors=errors)
        assert resp.data["errors"]["email"] == ["Invalid email."]

    def test_no_errors_when_not_provided(self):
        resp = error_response("Simple error")
        assert resp.data.get("errors") is None

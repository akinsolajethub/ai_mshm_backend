"""
core/exceptions/__init__.py
────────────────────────────
Custom exception hierarchy for AI-MSHM.
"""
from rest_framework import status
from rest_framework.exceptions import APIException


class ServiceException(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "A service error occurred."
    default_code = "service_error"


class TokenExpiredError(ServiceException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "The token has expired."
    default_code = "token_expired"


class TokenInvalidError(ServiceException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "The token is invalid."
    default_code = "token_invalid"


class EmailAlreadyVerifiedError(ServiceException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "This email address has already been verified."
    default_code = "email_already_verified"


class AccountNotActiveError(ServiceException):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "This account has been deactivated."
    default_code = "account_not_active"


class ResourceNotFoundError(ServiceException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "The requested resource was not found."
    default_code = "not_found"


class ResourceConflictError(ServiceException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "A resource with these details already exists."
    default_code = "conflict"


class OnboardingIncompleteError(ServiceException):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "Please complete your onboarding before accessing this feature."
    default_code = "onboarding_incomplete"


class InvalidOnboardingStepError(ServiceException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Invalid onboarding step."
    default_code = "invalid_step"


class WearableConnectionError(ServiceException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "Failed to connect to the wearable device service."
    default_code = "wearable_connection_error"


class CloudinaryUploadError(ServiceException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "Failed to upload file to storage."
    default_code = "upload_error"

"""
apps/accounts/serializers.py
─────────────────────────────
Serializers for authentication, registration, and user profile management.

REGISTRATION RULES:
  - Patients can self-register via RegisterSerializer (role defaults to 'patient').
  - PHC staff (hcc_staff) are created by HCC Admin via the centers API.
  - FMC staff (fhc_staff) and Clinicians are created by FHC Admin via the centers API.
  - PHC/FMC admins are created by Platform Admin via Django /admin/.
  - No one can self-register as 'admin', 'hcc_admin', 'fhc_admin', 'hcc_staff',
    'fhc_staff', or 'clinician' — attempting to do so returns a 400 error.

JWT PAYLOAD:
  The access token includes: email, role, name.
  The frontend uses the 'role' claim to determine which portal to show:
    patient   → Patient portal (purple, P1–P9)
    hcc_staff → PHC portal (green, PHC1–PHC9)
    hcc_admin → PHC portal (green, PHC9 staff management visible)
    fhc_staff → FMC portal (red, FMC1–FMC9)
    fhc_admin → FMC portal (red, FMC9 staff management visible)
    clinician → Clinician portal (navy, CL1–CL8)
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from core.validators import validate_image

User = get_user_model()

# Roles that cannot be self-registered — must be created by an admin
_RESTRICTED_ROLES = {
    User.Role.ADMIN,
    User.Role.HCC_ADMIN,
    User.Role.HCC_STAFF,
    User.Role.FHC_ADMIN,
    User.Role.FHC_STAFF,
    User.Role.CLINICIAN,
}


# ── JWT customisation ─────────────────────────────────────────────────────────

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Extends the default JWT token with user metadata embedded in the payload.

    Token claims added:
      - email  : user's email address
      - role   : user's role (used by frontend to route to correct portal)
      - name   : user's full name

    Login response also includes a 'user' key with the full UserProfileSerializer
    data so the frontend can populate the UI without an extra /me/ request.

    Raises 400 if the user's email is not verified.
    """

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["email"] = user.email
        token["role"]  = user.role
        token["name"]  = user.full_name
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        user = self.user

        if not user.is_email_verified:
            raise serializers.ValidationError({
                "email": "Please verify your email address before logging in.",
                "code":  "email_not_verified",
            })

        data["user"] = UserProfileSerializer(user).data
        return data


# ── Registration ──────────────────────────────────────────────────────────────

class RegisterSerializer(serializers.ModelSerializer):
    """
    Public self-registration serializer.

    Allowed roles: 'patient' only (default).
    All other roles (staff, admin, clinician) must be created via the
    admin panel or center management APIs — attempting to register with
    a restricted role returns a 400 validation error.

    Fields:
      full_name        : required
      email            : required, must be unique
      password         : required, validated against Django auth validators
      confirm_password : required, must match password
      role             : optional, defaults to 'patient'
    """
    password         = serializers.CharField(write_only=True, validators=[validate_password])
    confirm_password = serializers.CharField(write_only=True)

    class Meta:
        model  = User
        fields = ["full_name", "email", "password", "confirm_password", "role"]
        extra_kwargs = {
            "role": {"required": False},
        }

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate(self, attrs):
        if attrs["password"] != attrs.pop("confirm_password"):
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        return attrs

    def validate_role(self, value):
        if value in _RESTRICTED_ROLES:
            raise serializers.ValidationError(
                f"The role '{value}' cannot be self-registered. "
                "This account type must be created by an administrator."
            )
        return value

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


# ── Admin-created account serializers ────────────────────────────────────────

class CreateStaffAccountSerializer(serializers.Serializer):
    """
    Used by HCC Admin and FHC Admin to create new staff / clinician accounts.

    This serializer handles only the User record creation.
    The corresponding profile (HCCStaffProfile / FHCStaffProfile / ClinicianProfile)
    is created by the view after the user is created.

    The created user will receive a welcome email with a temporary password
    and a link to set their own password.

    Fields:
      full_name : required
      email     : required, must be unique
      role      : set programmatically by the view (not user-supplied)
    """
    full_name = serializers.CharField(max_length=255)
    email     = serializers.EmailField()

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email address already exists.")
        return value


# ── User profile (read-only, embedded in responses) ──────────────────────────

class UserProfileSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for the authenticated user's profile.

    Returned in:
      - Login response (inside the JWT data)
      - GET /api/v1/auth/me/
      - Account creation responses

    center_info field returns role-specific center context:
      - clinician  → {center_type, center_name, is_verified}
      - hcc_admin  → {center_type: 'phc', center_name}
      - hcc_staff  → {center_type: 'phc', center_name}
      - fhc_admin  → {center_type: 'fmc', center_name}
      - fhc_staff  → {center_type: 'fmc', center_name}
      - patient    → null
    """
    avatar_url  = serializers.SerializerMethodField()
    center_info = serializers.SerializerMethodField()
    id          = serializers.CharField(read_only=True)

    class Meta:
        model  = User
        fields = [
            "id", "email", "full_name", "role", "avatar_url",
            "is_email_verified", "onboarding_completed", "onboarding_step",
            "center_info", "date_joined",
        ]
        read_only_fields = fields

    def get_avatar_url(self, obj):
        request = self.context.get("request")
        if obj.avatar and request:
            return request.build_absolute_uri(obj.avatar.url)
        return None

    def get_center_info(self, obj):
        """Returns facility context for facility-affiliated roles."""
        if obj.role == "clinician":
            try:
                cp = obj.clinician_profile
                return {
                    "center_type": "fmc",
                    "center_name": cp.center_name,
                    "is_verified": cp.is_verified,
                }
            except Exception:
                return None

        if obj.role == "hcc_admin":
            try:
                return {"center_type": "phc", "center_name": obj.managed_hcc.name}
            except Exception:
                return None

        if obj.role == "hcc_staff":
            try:
                return {
                    "center_type": "phc",
                    "center_name": obj.hcc_staff_profile.hcc.name,
                }
            except Exception:
                return None

        if obj.role == "fhc_admin":
            try:
                return {"center_type": "fmc", "center_name": obj.managed_fhc.name}
            except Exception:
                return None

        if obj.role == "fhc_staff":
            try:
                return {
                    "center_type": "fmc",
                    "center_name": obj.fhc_staff_profile.fhc.name,
                }
            except Exception:
                return None

        return None


# ── Email verification ────────────────────────────────────────────────────────

class EmailVerificationSerializer(serializers.Serializer):
    """Accepts the raw verification token from the email link."""
    token = serializers.CharField()


class ResendVerificationSerializer(serializers.Serializer):
    """Triggers a new verification email for the given address."""
    email = serializers.EmailField()


# ── Password reset ────────────────────────────────────────────────────────────

class ForgotPasswordSerializer(serializers.Serializer):
    """Triggers a password reset email for the given address."""
    email = serializers.EmailField()


class ResetPasswordSerializer(serializers.Serializer):
    """
    Accepts the password reset token from the email link and sets a new password.
    The token is single-use and expires after PASSWORD_RESET_EXPIRY_HOURS.
    """
    token            = serializers.CharField()
    password         = serializers.CharField(validators=[validate_password])
    confirm_password = serializers.CharField()

    def validate(self, attrs):
        if attrs["password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        return attrs


# ── Change password (authenticated) ──────────────────────────────────────────

class ChangePasswordSerializer(serializers.Serializer):
    """
    Allows an authenticated user to change their password.
    Requires the current password as confirmation.
    """
    old_password = serializers.CharField()
    new_password = serializers.CharField(validators=[validate_password])

    def validate_old_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value


class ConfirmPasswordSerializer(serializers.Serializer):
    """
    Requires the user's current password before performing a destructive action
    (e.g. account deletion). Used as a final confirmation step.
    """
    password = serializers.CharField(help_text="Current password to confirm the action.")

    def validate_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Password is incorrect.")
        return value


# ── Logout ────────────────────────────────────────────────────────────────────

class LogoutSerializer(serializers.Serializer):
    """Blacklists the provided refresh token, invalidating the session."""
    refresh = serializers.CharField(help_text="The refresh token to blacklist.")


# ── Profile update ────────────────────────────────────────────────────────────

class UpdateProfileSerializer(serializers.ModelSerializer):
    """
    Allows an authenticated user to update their display name and avatar.
    Send as multipart/form-data when uploading an image.

    Fields:
      full_name : optional, minimum 5 characters
      avatar    : optional, JPEG/PNG/WebP, max 5 MB, uploaded to Cloudinary
    """
    avatar = serializers.ImageField(
        required=False,
        allow_null=True,
        error_messages={
            "invalid_image": "Unsupported file. Please upload a JPEG, PNG, or WebP image."
        },
    )
    full_name = serializers.CharField(required=False, allow_blank=False, min_length=5)

    class Meta:
        model  = User
        fields = ["full_name", "avatar"]

    def validate_avatar(self, value):
        return validate_image(value, max_mb=5)

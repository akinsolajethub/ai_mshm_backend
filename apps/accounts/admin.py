"""
apps/accounts/admin.py
───────────────────────
Django admin for User, EmailVerificationToken, and PasswordResetToken.

CREATING ADMIN ACCOUNTS (Platform Admin workflow):

  When creating HCC Admin or FHC Admin accounts via Django admin:
  1. Go to Users → Add User
  2. Fill in: email, full_name, role (PHC Admin or FMC Admin), password1, password2
  3. IMPORTANT: Set is_email_verified = True so the account can log in immediately
  4. Save, then go to the relevant PHC or FMC record and assign this user as admin_user

  Staff and Clinician accounts should be created via the API by facility admins,
  not manually here — unless troubleshooting or doing an admin override.
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, EmailVerificationToken, PasswordResetToken


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display    = ("email", "full_name", "role", "is_email_verified", "onboarding_completed", "date_joined")
    list_filter     = ("role", "is_email_verified", "onboarding_completed", "is_active")
    search_fields   = ("email", "full_name")
    ordering        = ("-date_joined",)
    readonly_fields = ("date_joined", "last_login")

    fieldsets = (
        (None,          {"fields": ("email", "password")}),
        ("Personal",    {"fields": ("full_name", "avatar")}),
        ("Role & Auth", {"fields": ("role", "is_email_verified", "onboarding_completed", "onboarding_step")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Timestamps",  {"fields": ("date_joined", "last_login")}),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": (
                "email", "full_name", "role",
                "password1", "password2",
                "is_email_verified",   # IMPORTANT: set True for admin/staff accounts so they can log in
            ),
        }),
    )


@admin.register(EmailVerificationToken)
class EmailVerificationTokenAdmin(admin.ModelAdmin):
    list_display  = ("user", "expires_at", "created_at")
    raw_id_fields = ("user",)
    readonly_fields = ("created_at",)


@admin.register(PasswordResetToken)
class PasswordResetTokenAdmin(admin.ModelAdmin):
    list_display  = ("user", "is_used", "expires_at", "created_at")
    list_filter   = ("is_used",)
    raw_id_fields = ("user",)
    readonly_fields = ("created_at",)
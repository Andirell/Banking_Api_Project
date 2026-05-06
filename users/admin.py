from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "id", "email", "first_name", "last_name",
        "role", "kyc_status", "created_at",
        "is_staff", "is_superuser"
    )
    search_fields = ("email", "first_name", "last_name", "phone_number", "bvn")
    list_filter = ("role", "kyc_status", "is_staff", "is_superuser", "is_active")
    readonly_fields = ("created_at", "last_login")
    ordering = ("-created_at",)

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {
            "fields": (
                "first_name", "last_name", "phone_number",
                "nationality", "date_of_birth", "address", "bvn",
            )
        }),
        ("Account info", {
            "fields": (
                "role", "kyc_status", "is_active",
                "is_staff", "is_superuser",
            )
        }),
        ("Permissions", {"fields": ("groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "created_at")}),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": (
                "email", "first_name", "last_name",
                "phone_number", "role", "password1", "password2",
            ),
        }),
    )
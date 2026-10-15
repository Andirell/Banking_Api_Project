from rest_framework.permissions import BasePermission


class IsKYCVerified(BasePermission):
    """Only customers whose KYC documents staff have verified."""

    message = "Complete KYC verification before using this feature."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.kyc_status == "verified")

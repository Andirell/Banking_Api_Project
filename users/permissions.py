from rest_framework.permissions import BasePermission


class IsKYCVerified(BasePermission):
    # Only lets in users whose KYC documents have been approved by staff
    message = "Complete KYC verification before using this feature."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return user.kyc_status == "verified"

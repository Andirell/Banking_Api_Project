import logging

from rest_framework.throttling import AnonRateThrottle

logger = logging.getLogger(__name__)


class OTPRateThrottle(AnonRateThrottle):
    """Per-IP limit for sign-in and the anonymous OTP endpoints (rate: DEFAULT_THROTTLE_RATES['otp'])."""

    scope = "otp"

    def get_ident(self, request):
        # TEMPORARY DIAGNOSTIC (remove after checking Render's proxy chain).
        meta = request.META
        logger.warning(
            "proxy-diag xff=%r remote=%r cf=%r true_client=%r x_real=%r ident=%r",
            meta.get("HTTP_X_FORWARDED_FOR"), meta.get("REMOTE_ADDR"), meta.get("HTTP_CF_CONNECTING_IP"),
            meta.get("HTTP_TRUE_CLIENT_IP"), meta.get("HTTP_X_REAL_IP"), super().get_ident(request),
        )
        return super().get_ident(request)


class SignupRateThrottle(AnonRateThrottle):
    """Per-IP limit on account creation, which also sends a welcome email (rate: DEFAULT_THROTTLE_RATES['signup'])."""

    scope = "signup"

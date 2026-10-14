from rest_framework.throttling import AnonRateThrottle


class OTPRateThrottle(AnonRateThrottle):
    """Per-IP limit for the anonymous OTP endpoints (rate: DEFAULT_THROTTLE_RATES['otp'])."""

    scope = "otp"

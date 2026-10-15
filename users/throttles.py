from rest_framework.throttling import AnonRateThrottle


class OTPRateThrottle(AnonRateThrottle):
    """Per-IP limit for sign-in and the anonymous OTP endpoints (rate: DEFAULT_THROTTLE_RATES['otp'])."""

    scope = "otp"


class SignupRateThrottle(AnonRateThrottle):
    """Per-IP limit on account creation, which also sends a welcome email (rate: DEFAULT_THROTTLE_RATES['signup'])."""

    scope = "signup"

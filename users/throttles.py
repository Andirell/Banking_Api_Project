from rest_framework.throttling import AnonRateThrottle

# The rates for these are in settings.py (DEFAULT_THROTTLE_RATES).
# Each one needs its own "scope" so they have separate counters.


class OTPRateThrottle(AnonRateThrottle):
    # Limits sign-in and the other OTP endpoints per IP address
    scope = "otp"


class SignupRateThrottle(AnonRateThrottle):
    # Limits how many accounts one IP address can create
    scope = "signup"

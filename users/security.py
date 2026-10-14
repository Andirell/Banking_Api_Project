"""OTP challenges and token revocation.

Every OTP lives in the database and belongs to one user and one purpose, so a
code can only ever authenticate the account it was issued to. Guessing is
capped per challenge and issuance is capped per account; both limits are in the
database, so new sessions or clients don't reset them.
"""

import hmac
import secrets
from datetime import timedelta

from django.db.models import F
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from .models import OTP

MAX_FAILED_ATTEMPTS = 5
MAX_CHALLENGES_PER_WINDOW = 3
CHALLENGE_WINDOW = timedelta(minutes=15)


class OTPRateLimited(Exception):
    pass


def generate_otp():
    return f"{secrets.randbelow(1_000_000):06d}"


def issue_otp(user, purpose):
    """Create a fresh challenge (retiring older ones) and return its code.

    Raises OTPRateLimited when the account has used its issuance budget.
    """
    recent = OTP.objects.filter(
        user=user, purpose=purpose, created_at__gte=timezone.now() - CHALLENGE_WINDOW
    ).count()
    if recent >= MAX_CHALLENGES_PER_WINDOW:
        raise OTPRateLimited()

    OTP.objects.filter(user=user, purpose=purpose, is_used=False).update(is_used=True)
    code = generate_otp()
    OTP.create_for_user(user, code, purpose=purpose)
    return code


def check_otp(user, purpose, submitted):
    """Return the active challenge if `submitted` matches it, else None.

    A wrong guess is counted atomically, and the challenge is retired once it
    reaches MAX_FAILED_ATTEMPTS.
    """
    otp = OTP.objects.filter(user=user, purpose=purpose, is_used=False).order_by("-created_at").first()
    if otp is None or otp.is_expired():
        return None

    if not hmac.compare_digest(otp.code, str(submitted or "")):
        OTP.objects.filter(pk=otp.pk).update(attempts=F("attempts") + 1)
        OTP.objects.filter(pk=otp.pk, attempts__gte=MAX_FAILED_ATTEMPTS).update(is_used=True)
        return None
    return otp


def consume_otp(otp_id, **conditions):
    """Mark a challenge used, only if it is still unused and unexpired.

    This is a single conditional UPDATE, so of two concurrent callers exactly
    one gets True. Callers must act only on True.
    """
    return OTP.objects.filter(
        pk=otp_id, is_used=False, expires_at__gt=timezone.now(), **conditions
    ).update(is_used=True) == 1


def revoke_user_tokens(user):
    """Blacklist every refresh token issued to `user`.

    Access tokens are already rejected once the password changes
    (SIMPLE_JWT CHECK_REVOKE_TOKEN); this covers refresh tokens too.
    """
    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)

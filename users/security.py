# Helpers for one-time passwords (OTPs) and for logging users out everywhere.
#
# How an OTP works here:
#   1. issue_otp(user, "signin")        -> makes a 6 digit code and saves it
#   2. we email the code to the user
#   3. check_otp(user, "signin", code)  -> is the code right?
#   4. consume_otp(otp.pk)              -> mark it used so it can't be used again
#
# Each code belongs to one user and one purpose, so a code sent to me can
# never log in someone else. The limits are stored in the database, so they
# still apply if someone uses a new browser or IP address.

import hmac
import secrets
from datetime import timedelta

from django.db.models import F
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from .models import OTP

MAX_FAILED_ATTEMPTS = 5          # wrong guesses allowed for one code
MAX_CHALLENGES_PER_WINDOW = 3    # codes we will send per account...
CHALLENGE_WINDOW = timedelta(minutes=15)  # ...in this much time


class OTPRateLimited(Exception):
    pass


def generate_otp():
    # secrets (not random) because the code must be impossible to predict
    number = secrets.randbelow(1_000_000)
    return f"{number:06d}"  # always 6 digits, e.g. 004213


def issue_otp(user, purpose):
    # Count how many codes this account asked for recently
    window_start = timezone.now() - CHALLENGE_WINDOW
    recent_codes = OTP.objects.filter(user=user, purpose=purpose, created_at__gte=window_start).count()
    if recent_codes >= MAX_CHALLENGES_PER_WINDOW:
        raise OTPRateLimited()

    # Old unused codes stop working once a new one is sent
    OTP.objects.filter(user=user, purpose=purpose, is_used=False).update(is_used=True)

    code = generate_otp()
    OTP.create_for_user(user, code, purpose=purpose)
    return code


def check_otp(user, purpose, submitted_code):
    # Returns the OTP row if the code is right, otherwise None.
    otp = OTP.objects.filter(user=user, purpose=purpose, is_used=False).order_by("-created_at").first()
    if otp is None or otp.is_expired():
        return None

    # compare_digest takes the same time whether the code is close or not,
    # so attackers can't guess the code by timing our answers
    if hmac.compare_digest(otp.code, str(submitted_code or "")):
        return otp

    # Wrong code: add 1 to the counter (in the database, so two requests at
    # once both count), and kill the code after too many wrong guesses
    OTP.objects.filter(pk=otp.pk).update(attempts=F("attempts") + 1)
    OTP.objects.filter(pk=otp.pk, attempts__gte=MAX_FAILED_ATTEMPTS).update(is_used=True)
    return None


def consume_otp(otp_id, **extra_conditions):
    # Mark the code as used, but only if it is still unused and not expired.
    #
    # This is one UPDATE query. If two requests try to use the same code at
    # the same moment, only one of them changes the row, so only one gets True.
    # Callers must only continue when this returns True.
    rows_updated = OTP.objects.filter(
        pk=otp_id, is_used=False, expires_at__gt=timezone.now(), **extra_conditions
    ).update(is_used=True)
    return rows_updated == 1


def revoke_user_tokens(user):
    # Log the user out on every device by blacklisting all their refresh tokens.
    # (Access tokens already stop working when the password changes, because
    # of CHECK_REVOKE_TOKEN in settings.py.)
    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)

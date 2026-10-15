"""Password authentication with a per-account lockout.

Every password check in the project (API sign-in and the Django admin login)
goes through Django's authenticate(), so the lockout lives here and covers both.
The counter is in the database, so it holds across workers, IPs and restarts.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import F
from django.utils import timezone

MAX_FAILED_SIGNINS = 5
LOCKOUT_PERIOD = timedelta(minutes=15)


class LockoutModelBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if username is None or password is None:
            return None

        try:
            user = UserModel._default_manager.get_by_natural_key(username)
        except UserModel.DoesNotExist:
            UserModel().set_password(password)  # same timing as a real check (#20760)
            return None

        now = timezone.now()
        if user.signin_locked_until and user.signin_locked_until > now:
            # Locked: refuse even the right password, and give no different answer.
            UserModel().set_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            if user.failed_signin_attempts:
                UserModel.objects.filter(pk=user.pk).update(failed_signin_attempts=0, signin_locked_until=None)
            return user

        # Counted atomically so parallel guesses can't slip past the limit.
        UserModel.objects.filter(pk=user.pk).update(failed_signin_attempts=F("failed_signin_attempts") + 1)
        UserModel.objects.filter(pk=user.pk, failed_signin_attempts__gte=MAX_FAILED_SIGNINS).update(
            failed_signin_attempts=0, signin_locked_until=now + LOCKOUT_PERIOD
        )
        return None

# Normal email + password login, plus a lockout:
# after 5 wrong passwords the account is locked for 15 minutes.
#
# Both the API sign-in and the Django admin login use authenticate(), which
# calls this backend, so the lockout protects both. The counter is saved in
# the database, so restarting the server or changing IP doesn't reset it.

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
            # Hash the password anyway so a wrong email takes as long as a
            # wrong password. Otherwise the timing tells attackers which
            # emails have accounts.
            UserModel().set_password(password)
            return None

        now = timezone.now()
        account_locked = user.signin_locked_until is not None and user.signin_locked_until > now
        if account_locked:
            # Refuse even the correct password, and take the same time
            UserModel().set_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            # Correct password: reset the counter
            if user.failed_signin_attempts:
                UserModel.objects.filter(pk=user.pk).update(failed_signin_attempts=0, signin_locked_until=None)
            return user

        # Wrong password: add 1 in the database (F() means two requests at
        # the same time both count) and lock the account if it reached the limit
        UserModel.objects.filter(pk=user.pk).update(failed_signin_attempts=F("failed_signin_attempts") + 1)
        UserModel.objects.filter(pk=user.pk, failed_signin_attempts__gte=MAX_FAILED_SIGNINS).update(
            failed_signin_attempts=0, signin_locked_until=now + LOCKOUT_PERIOD
        )
        return None

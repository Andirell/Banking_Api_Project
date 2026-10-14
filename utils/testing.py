"""Shared helpers for the test suites."""

import re
from decimal import Decimal

from django.core import mail
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import User
from wallets.models import Wallet

PASSWORD = "Str0ng-Passw0rd!"


def make_user(email, balance="0.00", **extra):
    user = User.objects.create_user(
        email=email, first_name="Test", last_name="User", password=PASSWORD, **extra
    )
    Wallet.objects.filter(user=user).update(balance=Decimal(balance))
    return user


def make_staff(email="staff@example.com"):
    return make_user(email, is_staff=True, role="admin")


def auth_client(user):
    """Return (client, refresh_token) authenticated as `user` with a real JWT pair."""
    refresh = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client, refresh


def balance_of(user):
    return Wallet.objects.get(user=user).balance


def last_emailed_code():
    """Extract the 6-digit code from the most recent outgoing email."""
    return re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)

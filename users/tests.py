import importlib
import io
import tempfile
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import jwt
from django.core import mail
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError
from django.db.models import ProtectedError
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

from loans.models import EMI, LoanApplication
from transactions.models import Transaction
from users.models import OTP, User
from utils.testing import PASSWORD, auth_client, last_emailed_code, make_staff, make_user

NEW_PASSWORD = "An0ther-Str0ng-Pass!"


class TokenRevocationTests(TestCase):
    """S2: a password change or reset must kill every token issued before it."""

    def setUp(self):
        cache.clear()
        self.user = make_user("victim@example.com")
        self.client, self.refresh = auth_client(self.user)

    def test_change_password_revokes_existing_tokens(self):
        res = self.client.post(
            "/users/change-password/",
            {"old_password": PASSWORD, "new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD},
            format="json",
        )

        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.client.get("/users/me/").status_code, 401)
        self.assertTrue(BlacklistedToken.objects.filter(token__jti=self.refresh["jti"]).exists())

    def test_password_reset_revokes_existing_tokens(self):
        anon = APIClient()
        anon.post("/users/request-password-reset/", {"email": self.user.email}, format="json")
        anon.post(
            "/users/verify-password-reset-otp/",
            {"email": self.user.email, "otp": last_emailed_code()},
            format="json",
        )
        res = anon.post(
            "/users/reset-password/",
            {"email": self.user.email, "new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD},
            format="json",
        )

        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.client.get("/users/me/").status_code, 401)
        self.assertTrue(BlacklistedToken.objects.filter(token__jti=self.refresh["jti"]).exists())


class SigningKeyTests(TestCase):
    """S5: there is no publicly known key that can sign accepted tokens."""

    OLD_FALLBACK = "django-insecure-local-development-key"

    def test_token_signed_with_old_fallback_is_rejected(self):
        user = make_user("victim@example.com")
        now = timezone.now()
        forged = jwt.encode(
            {"token_type": "access", "user_id": str(user.pk), "jti": "forged",
             "iat": int(now.timestamp()), "exp": int((now + timedelta(hours=1)).timestamp())},
            self.OLD_FALLBACK,
            algorithm="HS256",
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {forged}")

        self.assertEqual(client.get("/users/me/").status_code, 401)

    def test_debug_without_key_generates_and_persists_random_key(self):
        from my_fintech_app.secret_key import resolve_secret_key

        with tempfile.TemporaryDirectory() as tmp:
            key_file = Path(tmp) / ".dev_secret_key"
            first = resolve_secret_key(None, debug=True, key_file=key_file)
            second = resolve_secret_key(None, debug=True, key_file=key_file)

        self.assertNotEqual(first, self.OLD_FALLBACK)
        self.assertGreaterEqual(len(first), 50)
        self.assertEqual(first, second)

    def test_production_without_key_refuses_to_start(self):
        from my_fintech_app.secret_key import resolve_secret_key

        with self.assertRaises(ImproperlyConfigured):
            resolve_secret_key(None, debug=False, key_file=Path("/nonexistent/.dev_secret_key"))

    def test_configured_key_wins(self):
        from my_fintech_app.secret_key import resolve_secret_key

        self.assertEqual(resolve_secret_key("from-env", debug=True, key_file=Path("/nonexistent")), "from-env")


class AccountDeletionTests(TestCase):
    """S3/S7: closing an account never erases financial records."""

    def setUp(self):
        cache.clear()

    def test_borrower_with_unpaid_emi_cannot_delete(self):
        borrower = make_user("borrower@example.com")
        loan = LoanApplication.objects.create(
            user=borrower, amount=Decimal("1000.00"), duration_months=10, status="approved"
        )
        EMI.objects.create(loan=loan, due_date="2026-11-01", amount=Decimal("100.00"))
        client, _ = auth_client(borrower)

        res = client.delete("/users/delete/")

        self.assertEqual(res.status_code, 409)
        self.assertTrue(User.objects.get(pk=borrower.pk).is_active)
        self.assertEqual(EMI.objects.filter(loan=loan, is_paid=False).count(), 1)

    def test_user_with_funds_cannot_delete(self):
        client, _ = auth_client(make_user("rich@example.com", balance="5.00"))

        self.assertEqual(client.delete("/users/delete/").status_code, 409)

    def test_delete_deactivates_and_anonymises_but_keeps_history(self):
        user = make_user("leaver@example.com")
        Transaction.objects.create(sender=user, transaction_type="withdraw", amount=Decimal("1.00"), status="successful")
        client, _ = auth_client(user)

        res = client.delete("/users/delete/")

        self.assertEqual(res.status_code, 200)
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertNotIn("leaver", user.email)
        self.assertEqual(Transaction.objects.filter(sender=user).count(), 1)
        self.assertEqual(client.get("/users/me/").status_code, 401)

    def test_recipient_deleting_account_keeps_senders_transfer(self):
        sender = make_user("sender@example.com")
        recipient = make_user("recipient@example.com")
        tx = Transaction.objects.create(
            sender=sender, receiver=recipient, transaction_type="transfer", amount=Decimal("50.00"), status="successful"
        )
        from wallets.models import Wallet
        Wallet.objects.filter(user=recipient).update(balance=Decimal("0.00"))  # recipient spent it
        client, _ = auth_client(recipient)

        self.assertEqual(client.delete("/users/delete/").status_code, 200)
        self.assertTrue(Transaction.objects.filter(pk=tx.pk, amount=Decimal("50.00")).exists())

    def test_hard_delete_of_user_with_history_is_blocked(self):
        user = make_user("hard@example.com")
        Transaction.objects.create(sender=user, transaction_type="withdraw", amount=Decimal("1.00"), status="successful")

        with self.assertRaises(ProtectedError):
            user.delete()


def _png(name):
    buf = io.BytesIO()
    Image.new("RGB", (2, 2)).save(buf, format="PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


class KYCDocumentAccessTests(TestCase):
    """S6: identity documents are only readable by their owner or staff."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        override = override_settings(PRIVATE_MEDIA_ROOT=self._tmp.name)
        override.enable()
        self.addCleanup(override.disable)

        self.owner = make_user("owner@example.com")
        client, _ = auth_client(self.owner)
        res = client.post(
            "/users/kyc/submit/",
            {"identity_document": _png("passport.png"), "proof_of_address": _png("bill.png")},
            format="multipart",
        )
        self.assertEqual(res.status_code, 200)
        self.url = f"/users/kyc/documents/{self.owner.pk}/identity/"

    def test_media_route_is_not_registered_even_in_debug(self):
        import my_fintech_app.urls as root_urls

        with override_settings(DEBUG=True):
            reloaded = importlib.reload(root_urls)
            patterns = [str(p.pattern) for p in reloaded.urlpatterns]
        importlib.reload(root_urls)

        self.assertFalse(any("media" in p for p in patterns), patterns)

    def test_documents_are_stored_outside_media_root(self):
        self.owner.refresh_from_db()
        stored = Path(self.owner.identity_document.path)

        self.assertTrue(stored.is_relative_to(self._tmp.name))

    def test_owner_can_download(self):
        client, _ = auth_client(self.owner)
        res = client.get(self.url)

        self.assertEqual(res.status_code, 200)
        self.assertTrue(b"".join(res.streaming_content).startswith(b"\x89PNG"))

    def test_staff_can_download(self):
        client, _ = auth_client(make_staff())

        self.assertEqual(client.get(self.url).status_code, 200)

    def test_other_customer_cannot_download(self):
        client, _ = auth_client(make_user("snoop@example.com"))

        self.assertEqual(client.get(self.url).status_code, 404)

    def test_anonymous_cannot_download(self):
        self.assertEqual(APIClient().get(self.url).status_code, 401)


class SigninOTPTests(TestCase):
    """S9/S10: one challenge, one login, bound to the account that passed the password check."""

    def setUp(self):
        cache.clear()
        self.user = make_user("user@example.com")
        self.client = APIClient()

    def signin(self, email="user@example.com"):
        return self.client.post("/users/signin/", {"email": email, "password": PASSWORD}, format="json")

    def verify(self, code, email="user@example.com"):
        return self.client.post("/users/verify-signin-otp/", {"email": email, "otp": code}, format="json")

    def test_code_works_once(self):
        self.signin()
        code = last_emailed_code()

        self.assertIn("access_token", self.verify(code).data)
        self.assertEqual(self.verify(code).status_code, 400)

    def test_concurrent_consumption_issues_tokens_once(self):
        self.signin()
        code = last_emailed_code()
        real_is_expired = OTP.is_expired

        def other_request_consumes_first(otp_self):
            OTP.objects.filter(pk=otp_self.pk).update(is_used=True)
            return real_is_expired(otp_self)

        with patch.object(OTP, "is_expired", other_request_consumes_first):
            res = self.verify(code)

        self.assertEqual(res.status_code, 400)
        self.assertNotIn("access_token", res.data)

    def test_signin_fails_closed_when_otp_cannot_be_stored(self):
        with patch.object(OTP, "create_for_user", side_effect=DatabaseError("db down")):
            res = self.signin()

        self.assertEqual(res.status_code, 503)
        self.assertNotIn("otp_code", self.client.session)

    def test_session_code_cannot_log_in_as_someone_else(self):
        make_user("attacker@example.com")
        session = self.client.session
        session["otp_code"] = "123456"  # attacker-owned session challenge
        session["otp_expiry"] = timezone.now().timestamp() + 300
        session.save()

        with patch.object(OTP.objects, "filter", side_effect=DatabaseError("db down")):
            res = self.verify("123456", email="user@example.com")

        self.assertNotIn("access_token", res.data or {})

    def test_wrong_guesses_burn_the_challenge(self):
        self.signin()
        code = last_emailed_code()
        for _ in range(5):
            self.verify("000000" if code != "000000" else "111111")

        self.assertEqual(self.verify(code).status_code, 400)


class PasswordResetTests(TestCase):
    """S11/S12: recovery codes are rate limited, single use and expire."""

    def setUp(self):
        cache.clear()
        self.user = make_user("user@example.com")
        self.client = APIClient()

    def request_reset(self, client=None):
        return (client or self.client).post(
            "/users/request-password-reset/", {"email": self.user.email}, format="json"
        )

    def verify(self, code, client=None):
        return (client or self.client).post(
            "/users/verify-password-reset-otp/", {"email": self.user.email, "otp": code}, format="json"
        )

    def reset(self, client=None):
        return (client or self.client).post(
            "/users/reset-password/",
            {"email": self.user.email, "new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD},
            format="json",
        )

    def password_changed(self):
        self.user.refresh_from_db()
        return self.user.check_password(NEW_PASSWORD)

    def test_happy_path(self):
        self.request_reset()
        self.assertEqual(self.verify(last_emailed_code()).status_code, 200)
        self.assertEqual(self.reset().status_code, 200)
        self.assertTrue(self.password_changed())

    def test_challenge_dies_after_five_wrong_guesses_across_sessions(self):
        self.request_reset()
        code = last_emailed_code()
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(5):
            self.verify(wrong, client=APIClient())  # fresh session each guess

        self.assertEqual(self.verify(code).status_code, 400)
        self.assertEqual(self.reset().status_code, 400)
        self.assertFalse(self.password_changed())

    def test_issuance_budget_per_account(self):
        for _ in range(3):
            self.request_reset(client=APIClient())
        self.assertEqual(OTP.objects.filter(user=self.user, purpose="password_reset").count(), 3)
        emails_before = len(mail.outbox)

        res = self.request_reset(client=APIClient())

        self.assertEqual(res.status_code, 200)  # same answer as unknown emails: no enumeration
        self.assertEqual(OTP.objects.filter(user=self.user, purpose="password_reset").count(), 3)
        self.assertEqual(len(mail.outbox), emails_before)

    def test_verified_grant_expires(self):
        self.request_reset()
        self.verify(last_emailed_code())

        later = timezone.now() + timedelta(minutes=6)
        with patch("django.utils.timezone.now", return_value=later):
            res = self.reset()

        self.assertEqual(res.status_code, 400)
        self.assertFalse(self.password_changed())

    def test_one_verification_allows_one_reset(self):
        self.request_reset()
        self.verify(last_emailed_code())

        self.assertEqual(self.reset().status_code, 200)
        self.assertEqual(self.reset().status_code, 400)


class EmailFailureTests(TestCase):
    """Production can't always reach the mail server (e.g. Render free blocks SMTP)."""

    def setUp(self):
        cache.clear()

    def test_signup_succeeds_when_welcome_email_fails(self):
        with patch("users.signals.send_smtp_mail", side_effect=OSError("smtp unreachable")) as mailer, \
                self.captureOnCommitCallbacks(execute=True):
            res = APIClient().post(
                "/users/signup/",
                {"first_name": "New", "last_name": "User", "email": "new@example.com",
                 "password": PASSWORD, "confirm_password": PASSWORD},
                format="json",
            )

        self.assertEqual(res.status_code, 201)
        self.assertTrue(User.objects.filter(email="new@example.com").exists())
        mailer.assert_called_once()  # the email really was attempted (and failed)

    def test_signin_reports_undeliverable_code(self):
        make_user("user@example.com")
        with patch("users.views.send_mail", side_effect=OSError("smtp unreachable")):
            res = APIClient().post(
                "/users/signin/", {"email": "user@example.com", "password": PASSWORD}, format="json"
            )

        self.assertEqual(res.status_code, 503)
        self.assertFalse(OTP.objects.filter(user__email="user@example.com", is_used=False).exists())

    def test_email_has_a_timeout(self):
        from django.conf import settings

        self.assertTrue(settings.EMAIL_TIMEOUT)

    @override_settings(EMAIL_BACKEND="anymail.backends.test.EmailBackend")
    def test_otp_is_delivered_through_an_http_email_api(self):
        make_user("user@example.com")
        res = APIClient().post(
            "/users/signin/", {"email": "user@example.com", "password": PASSWORD}, format="json"
        )

        self.assertEqual(res.status_code, 200)
        self.assertEqual(mail.outbox[-1].to, ["user@example.com"])
        self.assertIn(last_emailed_code(), mail.outbox[-1].body)


class GenericOTPTests(TestCase):
    """The generic send/verify OTP endpoints use the same DB-backed challenges as sign-in."""

    def setUp(self):
        cache.clear()
        self.user = make_user("user@example.com")
        self.client, _ = auth_client(self.user)

    def send(self):
        return self.client.post("/users/send-otp/")

    def verify(self, code, client=None):
        return (client or self.client).post("/users/verify-otp/", {"otp": code}, format="json")

    def test_code_is_stored_in_db_not_session(self):
        self.send()

        self.assertTrue(OTP.objects.filter(user=self.user, purpose="verify", is_used=False).exists())
        self.assertNotIn("otp_code", self.client.session)

    def test_code_works_once(self):
        self.send()
        code = last_emailed_code()

        self.assertEqual(self.verify(code).status_code, 200)
        self.assertEqual(self.verify(code).status_code, 400)

    def test_code_is_bound_to_its_user(self):
        self.send()
        code = last_emailed_code()

        other, _ = auth_client(make_user("other@example.com"))
        self.assertEqual(self.verify(code, client=other).status_code, 400)

    def test_signin_code_is_not_accepted(self):
        OTP.create_for_user(self.user, "123456", purpose="signin")

        self.assertEqual(self.verify("123456").status_code, 400)

    def test_expired_code_is_rejected(self):
        self.send()
        code = last_emailed_code()
        OTP.objects.filter(user=self.user).update(expires_at=timezone.now() - timedelta(seconds=1))

        self.assertEqual(self.verify(code).status_code, 400)

    def test_wrong_guesses_burn_the_challenge(self):
        self.send()
        code = last_emailed_code()
        for _ in range(5):
            self.verify("000000" if code != "000000" else "111111")

        self.assertEqual(self.verify(code).status_code, 400)

    def test_issuance_is_capped(self):
        for _ in range(3):
            self.assertEqual(self.send().status_code, 200)

        self.assertEqual(self.send().status_code, 429)

    def test_email_failure_returns_503_and_retires_code(self):
        with patch("users.views.send_mail", side_effect=OSError("smtp down")):
            res = self.send()

        self.assertEqual(res.status_code, 503)
        self.assertFalse(OTP.objects.filter(user=self.user, purpose="verify", is_used=False).exists())


class ProductionSecuritySettingsTests(TestCase):
    """With DEBUG off, `check --deploy` raises no HTTPS / cookie / HSTS warnings."""

    def test_deploy_check_is_clean(self):
        import os
        import subprocess
        import sys

        env = {
            **os.environ,
            "RENDER": "true",
            "DEBUG": "false",
            "SECRET_KEY": "x9-" + "q7Lm2Zr8Vt4Kw1Np6Hs3Jd5Fb0Gc" * 3,
            "ALLOWED_HOSTS": "example.com",
        }
        result = subprocess.run(
            [sys.executable, "manage.py", "check", "--deploy", "--fail-level", "WARNING"],
            cwd=Path(__file__).resolve().parent.parent,
            env=env,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

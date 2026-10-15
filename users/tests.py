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
from rest_framework_simplejwt.tokens import RefreshToken

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


class SigninLockoutTests(TestCase):
    """N1: password guessing is capped per account (API and admin) and per IP."""

    def setUp(self):
        cache.clear()
        self.user = make_user("user@example.com")
        self.client = APIClient()

    def signin(self, password=PASSWORD, ip="198.51.100.1"):
        return self.client.post(
            "/users/signin/", {"email": "user@example.com", "password": password},
            format="json", REMOTE_ADDR=ip,
        )

    def fail(self, times):
        # Spread over many IPs so only the per-account lockout is being tested.
        for i in range(times):
            self.signin("wrong-password", ip=f"198.51.100.{10 + i}")

    def test_correct_password_refused_after_five_failures(self):
        self.fail(5)
        res = self.signin()

        self.assertEqual(res.status_code, 401)
        self.assertEqual(len(mail.outbox), 0)

    def test_four_failures_do_not_lock(self):
        self.fail(4)

        self.assertEqual(self.signin().status_code, 200)

    def test_success_resets_the_counter(self):
        self.fail(4)
        self.signin()
        self.fail(4)

        self.assertEqual(self.signin().status_code, 200)

    def test_lock_expires(self):
        self.fail(5)
        User.objects.filter(pk=self.user.pk).update(signin_locked_until=timezone.now() - timedelta(seconds=1))

        self.assertEqual(self.signin().status_code, 200)

    @override_settings(STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    })
    def test_admin_login_is_locked_too(self):
        staff = make_staff()
        for _ in range(5):
            self.client.post("/admin/login/", {"username": staff.email, "password": "wrong-password"})
        self.client.post("/admin/login/", {"username": staff.email, "password": PASSWORD})

        self.assertFalse(self.client.session.get("_auth_user_id"), "admin login succeeded while locked")

    def test_password_reset_clears_the_lock(self):
        self.fail(5)
        self.client.post("/users/request-password-reset/", {"email": "user@example.com"}, format="json")
        self.client.post(
            "/users/verify-password-reset-otp/",
            {"email": "user@example.com", "otp": last_emailed_code()}, format="json",
        )
        self.client.post(
            "/users/reset-password/",
            {"email": "user@example.com", "new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD},
            format="json",
        )

        self.assertEqual(self.signin(NEW_PASSWORD).status_code, 200)

    def test_signin_is_throttled_per_ip(self):
        for _ in range(10):
            self.client.post(
                "/users/signin/", {"email": "nobody@example.com", "password": "x"},
                format="json", REMOTE_ADDR="198.51.100.1",
            )

        self.assertEqual(self.signin().status_code, 429)


class ThrottleIdentityTests(TestCase):
    """N2: a client-supplied X-Forwarded-For prefix can't give each request a fresh rate-limit bucket."""

    def setUp(self):
        cache.clear()

    def test_spoofed_forwarded_for_does_not_reset_the_limit(self):
        client = APIClient()
        for i in range(11):
            # What Render forwards: the client's fake value, then the real address it appended.
            res = client.post(
                "/users/verify-signin-otp/", {"email": "a@example.com", "otp": "000000"}, format="json",
                HTTP_X_FORWARDED_FOR=f"10.0.0.{i}, 203.0.113.7",
            )

        self.assertEqual(res.status_code, 429)


SIGNUP = {
    "first_name": "New", "last_name": "Customer", "email": "new@example.com",
    "password": PASSWORD, "confirm_password": PASSWORD,
}


class SignupPrivacyTests(TestCase):
    """N6/N7: sign-up doesn't reveal registered BVNs or phones, and is rate limited."""

    def setUp(self):
        cache.clear()
        make_user("existing@example.com", bvn="12345678901", phone_number="08030000000")

    def signup(self, **fields):
        return APIClient().post("/users/signup/", {**SIGNUP, **fields}, format="json")

    def test_taken_bvn_and_phone_get_the_same_generic_answer(self):
        by_bvn = self.signup(bvn="12345678901")
        by_phone = self.signup(email="new2@example.com", phone_number="08030000000")

        self.assertEqual(by_bvn.status_code, 400)
        self.assertEqual(by_bvn.data, by_phone.data)
        self.assertNotIn("bvn", str(by_bvn.data).lower())
        self.assertNotIn("phone", str(by_phone.data).lower())

    def test_duplicate_phone_is_a_400_not_a_500(self):
        from users.serializers import UserSerializer

        # A concurrent sign-up takes the number after the pre-check has passed.
        with patch.object(UserSerializer, "validate", lambda self, attrs: attrs):
            res = self.signup(phone_number="08030000000")

        self.assertEqual(res.status_code, 400)

    def test_bvn_must_be_11_digits(self):
        self.assertEqual(self.signup(bvn="12345").status_code, 400)

    def test_profile_masks_bvn(self):
        client, _ = auth_client(User.objects.get(email="existing@example.com"))
        res = client.get("/users/me/")

        self.assertEqual(res.data["bvn"], "*******8901")

    def test_signup_is_rate_limited_per_ip(self):
        for i in range(5):
            self.assertEqual(self.signup(email=f"user{i}@example.com").status_code, 201)

        self.assertEqual(self.signup(email="user5@example.com").status_code, 429)


class KYCReviewTests(TestCase):
    """N8: approval needs documents, and new documents reset an earlier approval."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        override = override_settings(PRIVATE_MEDIA_ROOT=self._tmp.name)
        override.enable()
        self.addCleanup(override.disable)
        self.customer = make_user("customer@example.com", kyc_status="pending")
        self.staff, _ = auth_client(make_staff())

    def submit(self):
        client, _ = auth_client(self.customer)
        return client.post(
            "/users/kyc/submit/",
            {"identity_document": _png("passport.png"), "proof_of_address": _png("bill.png")},
            format="multipart",
        )

    def approve(self):
        return self.staff.post(f"/users/kyc/admin/approve/{self.customer.pk}/", {"kyc_status": "verified"}, format="json")

    def test_cannot_approve_without_documents(self):
        self.assertEqual(self.approve().status_code, 400)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.kyc_status, "pending")

    def test_resubmission_resets_approval_and_deletes_old_files(self):
        self.submit()
        self.approve()
        self.customer.refresh_from_db()
        old_path = Path(self.customer.identity_document.path)

        self.submit()
        self.customer.refresh_from_db()

        self.assertEqual(self.customer.kyc_status, "pending")
        self.assertFalse(self.customer.kyc_approved)
        self.assertFalse(old_path.exists())
        self.assertTrue(Path(self.customer.identity_document.path).exists())


class AccountClosureRaceTests(TestCase):
    """N9: money that arrives during closure blocks it; closed accounts stay closed."""

    def setUp(self):
        self.user = make_user("closing@example.com")
        self.client, _ = auth_client(self.user)

    def test_credit_landing_after_the_first_look_blocks_closure(self):
        from wallets import services
        from wallets.models import Wallet

        def transfer_lands_first(*user_ids):
            Wallet.objects.filter(user_id=self.user.pk).update(balance=Decimal("5.00"))
            return services.lock_wallets(*user_ids)

        with patch("users.views.lock_wallets", side_effect=transfer_lands_first):
            res = self.client.delete("/users/delete/")

        self.assertEqual(res.status_code, 409)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_closed_account_cannot_be_unblocked(self):
        self.client.delete("/users/delete/")
        admin, _ = auth_client(make_staff())

        res = admin.patch(f"/users/unblock/{self.user.pk}/")

        self.assertEqual(res.status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_blocked_account_can_still_be_unblocked(self):
        admin, _ = auth_client(make_staff())
        admin.patch(f"/users/block/{self.user.pk}/")

        self.assertEqual(admin.patch(f"/users/unblock/{self.user.pk}/").status_code, 200)


class TokenLifetimeTests(TestCase):
    """N10: short access tokens; refresh tokens rotate and work once."""

    def setUp(self):
        self.user = make_user("user@example.com")
        self.refresh = str(RefreshToken.for_user(self.user))

    def refresh_with(self, token):
        return APIClient().post("/users/token/refresh/", {"refresh": token}, format="json")

    def test_access_token_lives_at_most_15_minutes(self):
        access = RefreshToken.for_user(self.user).access_token

        self.assertLessEqual(access["exp"] - access["iat"], 15 * 60)

    def test_refresh_rotates_and_old_token_is_single_use(self):
        first = self.refresh_with(self.refresh)

        self.assertEqual(first.status_code, 200)
        self.assertIn("access", first.data)
        self.assertNotEqual(first.data["refresh"], self.refresh)
        self.assertEqual(self.refresh_with(self.refresh).status_code, 401)

    def test_refresh_refused_after_password_change(self):
        client, _ = auth_client(self.user)
        client.post(
            "/users/change-password/",
            {"old_password": PASSWORD, "new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD},
            format="json",
        )

        self.assertEqual(self.refresh_with(self.refresh).status_code, 401)


class EmailCaseTests(TestCase):
    """N12: an email identifies one account whatever its case."""

    def setUp(self):
        cache.clear()

    def test_signup_with_different_case_is_a_duplicate(self):
        make_user("alice@example.com")
        res = APIClient().post("/users/signup/", {**SIGNUP, "email": "Alice@Example.com"}, format="json")

        self.assertEqual(res.status_code, 400)
        self.assertEqual(User.objects.filter(email__iexact="alice@example.com").count(), 1)

    def test_email_is_stored_lowercase_and_signin_ignores_case(self):
        make_user("Bob@Example.COM")

        self.assertTrue(User.objects.filter(email="bob@example.com").exists())
        res = APIClient().post("/users/signin/", {"email": "BOB@example.com", "password": PASSWORD}, format="json")
        self.assertEqual(res.status_code, 200)

    def test_database_rejects_case_variant(self):
        from django.db import IntegrityError, transaction

        make_user("carol@example.com")
        other = make_user("other@example.com")
        # .update() bypasses save()'s lowercasing, so only the DB constraint can stop this.
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.filter(pk=other.pk).update(email="CAROL@example.com")


class APIDocsVisibilityTests(TestCase):
    """N13: Swagger and the schema are served only when API_DOCS_PUBLIC is on."""

    def urls_with(self, public):
        import my_fintech_app.urls as root_urls

        with override_settings(API_DOCS_PUBLIC=public):
            patterns = [str(p.pattern) for p in importlib.reload(root_urls).urlpatterns]
        importlib.reload(root_urls)
        return patterns

    def test_docs_hidden_when_switched_off(self):
        patterns = self.urls_with(False)

        self.assertNotIn("api/docs/", patterns)
        self.assertNotIn("api/schema/", patterns)

    def test_docs_served_when_switched_on(self):
        self.assertIn("api/docs/", self.urls_with(True))

    def test_production_default_is_off(self):
        import os
        import subprocess
        import sys

        env = {**os.environ, "RENDER": "true", "DEBUG": "false", "SECRET_KEY": "k" * 60}
        env.pop("API_DOCS_PUBLIC", None)
        out = subprocess.run(
            [sys.executable, "-c", "import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'my_fintech_app.settings'); "
             "from django.conf import settings; print(settings.API_DOCS_PUBLIC)"],
            cwd=Path(__file__).resolve().parent.parent, env=env, capture_output=True, text=True,
        )

        self.assertEqual(out.stdout.strip(), "False", out.stderr)


class LogoutOwnershipTests(TestCase):
    """N16: you can only end your own session."""

    def test_cannot_blacklist_someone_elses_refresh_token(self):
        victim_refresh = RefreshToken.for_user(make_user("victim@example.com"))
        client, _ = auth_client(make_user("attacker@example.com"))

        res = client.post("/users/logout/", {"refresh_token": str(victim_refresh)}, format="json")

        self.assertEqual(res.status_code, 400)
        self.assertFalse(BlacklistedToken.objects.filter(token__jti=victim_refresh["jti"]).exists())

    def test_own_token_is_blacklisted(self):
        client, refresh = auth_client(make_user("user@example.com"))

        res = client.post("/users/logout/", {"refresh_token": str(refresh)}, format="json")

        self.assertEqual(res.status_code, 200)
        self.assertTrue(BlacklistedToken.objects.filter(token__jti=refresh["jti"]).exists())


class WelcomeEmailTests(TestCase):
    """N17: the welcome email uses the configured sender and never links to localhost."""

    def signup(self):
        cache.clear()
        with self.captureOnCommitCallbacks(execute=True):
            APIClient().post("/users/signup/", SIGNUP, format="json")
        return mail.outbox[-1]

    @override_settings(DEFAULT_FROM_EMAIL="hello@vampay.example", FRONTEND_URL="https://app.vampay.example")
    def test_uses_configured_sender_and_frontend(self):
        email = self.signup()
        html = email.alternatives[0][0]

        self.assertEqual(email.from_email, "hello@vampay.example")
        self.assertIn("https://app.vampay.example/onboarding", html)
        self.assertNotIn("localhost", html)

    @override_settings(FRONTEND_URL="")
    def test_no_button_without_frontend(self):
        html = self.signup().alternatives[0][0]

        self.assertNotIn("localhost", html)
        self.assertNotIn("/onboarding", html)

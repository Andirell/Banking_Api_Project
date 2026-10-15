from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from analytics.models import SuspiciousActivity
from transactions.models import Transaction
from users.models import User
from utils.testing import auth_client, balance_of, make_staff, make_user
from wallets import services


class DepositAuthorizationTests(TestCase):
    """S1: a customer's requested amount must never create wallet credit."""

    def setUp(self):
        self.customer = make_user("customer@example.com")
        self.staff = make_staff()

    def test_customer_cannot_credit_own_wallet(self):
        client, _ = auth_client(self.customer)
        res = client.post("/transactions/deposit/", {"amount": "1000000.00"}, format="json")

        self.assertEqual(res.status_code, 403)
        self.assertEqual(balance_of(self.customer), Decimal("0.00"))
        self.assertFalse(Transaction.objects.exists())

    def test_staff_funding_credits_once_per_reference(self):
        client, _ = auth_client(self.staff)
        payload = {"user_id": self.customer.pk, "amount": "250.00", "funding_reference": "BANK-REF-001"}

        first = client.post("/transactions/deposit/", payload, format="json")
        second = client.post("/transactions/deposit/", payload, format="json")

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(balance_of(self.customer), Decimal("250.00"))

    def test_staff_funding_requires_reference(self):
        client, _ = auth_client(self.staff)
        res = client.post(
            "/transactions/deposit/", {"user_id": self.customer.pk, "amount": "250.00"}, format="json"
        )

        self.assertEqual(res.status_code, 400)
        self.assertEqual(balance_of(self.customer), Decimal("0.00"))


class TransferTests(TestCase):
    def setUp(self):
        self.alice = make_user("alice@example.com", balance="10000.00")
        self.bob = make_user("bob@example.com")
        self.client, _ = auth_client(self.alice)

    def send(self, amount, to="bob@example.com"):
        return self.client.post(
            "/transactions/send/", {"receiver_email": to, "amount": amount}, format="json"
        )

    def test_transfer_moves_funds(self):
        res = self.send("100.00")

        self.assertEqual(res.status_code, 201)
        self.assertEqual(balance_of(self.alice), Decimal("9900.00"))
        self.assertEqual(balance_of(self.bob), Decimal("100.00"))

    def test_insufficient_funds_changes_nothing(self):
        res = self.send("10000.01")

        self.assertEqual(res.status_code, 400)
        self.assertEqual(balance_of(self.alice), Decimal("10000.00"))
        self.assertEqual(balance_of(self.bob), Decimal("0.00"))


class TransferMonitoringTests(TestCase):
    """S8: successful transfers must enter the fraud-monitoring pipeline."""

    def setUp(self):
        self.alice = make_user("alice@example.com", balance="10000.00")
        self.bob = make_user("bob@example.com")
        self.client, _ = auth_client(self.alice)

    def test_large_transfer_is_flagged(self):
        res = self.client.post(
            "/transactions/send/", {"receiver_email": "bob@example.com", "amount": "6000.00"}, format="json"
        )

        self.assertEqual(res.status_code, 201)
        flag = SuspiciousActivity.objects.get(transaction__id=res.data["transaction"]["id"])
        self.assertIn("high_transfer_amount", flag.reason)

    def test_scorer_failure_is_recorded_not_swallowed(self):
        with patch("analytics.utils.simple_flagTransaction", side_effect=RuntimeError("scorer down")):
            res = self.client.post(
                "/transactions/send/", {"receiver_email": "bob@example.com", "amount": "10.00"}, format="json"
            )

        self.assertEqual(res.status_code, 201)
        self.assertTrue(
            SuspiciousActivity.objects.filter(
                transaction__id=res.data["transaction"]["id"], reason="monitoring_failed"
            ).exists()
        )


class KYCTransactionRulesTests(TestCase):
    """N8: withdrawals need verified KYC; unverified customers can only send small transfers."""

    def setUp(self):
        cache.clear()
        self.unverified = make_user("new@example.com", balance="10000.00", kyc_status="pending")
        make_user("bob@example.com")
        self.client, _ = auth_client(self.unverified)

    def test_unverified_customer_cannot_withdraw(self):
        res = self.client.post("/transactions/withdraw/", {"amount": "10.00"}, format="json")

        self.assertEqual(res.status_code, 403)
        self.assertEqual(balance_of(self.unverified), Decimal("10000.00"))

    def test_unverified_transfer_limit(self):
        small = self.client.post("/transactions/send/", {"receiver_email": "bob@example.com", "amount": "5000.00"}, format="json")
        large = self.client.post("/transactions/send/", {"receiver_email": "bob@example.com", "amount": "5000.01"}, format="json")

        self.assertEqual(small.status_code, 201)
        self.assertEqual(large.status_code, 403)
        self.assertEqual(balance_of(self.unverified), Decimal("5000.00"))


class StaffAuditTests(TestCase):
    """N5: a deposit records which staff member made it."""

    def test_deposit_records_staff_member(self):
        staff = make_staff()
        customer = make_user("customer@example.com")
        client, _ = auth_client(staff)

        client.post(
            "/transactions/deposit/",
            {"user_id": customer.pk, "amount": "50.00", "funding_reference": "BANK-REF-9"},
            format="json",
        )

        self.assertEqual(Transaction.objects.get(funding_reference="BANK-REF-9").created_by, staff)


class ReceiverPrivacyAndClosureTests(TestCase):
    """N9/N11: no credits to closed accounts, and no way to probe which emails exist."""

    def setUp(self):
        cache.clear()
        self.alice = make_user("alice@example.com", balance="1000.00")
        self.bob = make_user("bob@example.com")
        self.client, _ = auth_client(self.alice)

    def send(self, to, amount="10.00"):
        return self.client.post("/transactions/send/", {"receiver_email": to, "amount": amount}, format="json")

    def test_unknown_and_closed_receivers_get_the_same_answer(self):
        User.objects.filter(pk=self.bob.pk).update(is_active=False)

        unknown = self.send("nobody@example.com")
        closed = self.send("bob@example.com")

        self.assertEqual(unknown.status_code, 400)
        self.assertEqual(unknown.data, closed.data)

    def test_receiver_closed_after_lookup_gets_nothing(self):
        def account_closes_first(*user_ids):
            User.objects.filter(pk=self.bob.pk).update(is_active=False)
            return services.lock_wallets(*user_ids)

        with patch("transactions.views.lock_wallets", side_effect=account_closes_first):
            res = self.send("bob@example.com")

        self.assertEqual(res.status_code, 400)
        self.assertEqual(balance_of(self.alice), Decimal("1000.00"))
        self.assertEqual(balance_of(self.bob), Decimal("0.00"))

    def test_deposit_to_account_closed_after_lookup_is_refused(self):
        staff, _ = auth_client(make_staff())

        def account_closes_first(*user_ids):
            User.objects.filter(pk=self.bob.pk).update(is_active=False)
            return services.lock_wallets(*user_ids)

        with patch("transactions.views.lock_wallets", side_effect=account_closes_first):
            res = staff.post(
                "/transactions/deposit/",
                {"user_id": self.bob.pk, "amount": "50.00", "funding_reference": "BANK-REF-10"},
                format="json",
            )

        self.assertEqual(res.status_code, 400)
        self.assertEqual(balance_of(self.bob), Decimal("0.00"))

    def test_transfers_are_rate_limited_per_user(self):
        for _ in range(30):
            self.send("nobody@example.com")

        self.assertEqual(self.send("bob@example.com").status_code, 429)

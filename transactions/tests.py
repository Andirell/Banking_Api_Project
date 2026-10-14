from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from analytics.models import SuspiciousActivity
from transactions.models import Transaction
from utils.testing import auth_client, balance_of, make_staff, make_user


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

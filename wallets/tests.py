import threading
from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch

from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase

from analytics.models import SuspiciousActivity
from transactions.models import Transaction
from utils.testing import auth_client, balance_of, make_staff, make_user
from wallets import services
from wallets.models import Wallet


class WalletServiceStaleSnapshotTests(TestCase):
    """S4/S13: a balance write must never be computed from an earlier read.

    Each test loads a wallet, lets a "concurrent" writer commit, then hands the
    stale instance to the service. A read-modify-save implementation would
    overwrite the concurrent change; an F() update keeps both.
    """

    def setUp(self):
        self.user = make_user("owner@example.com", balance="100.00")

    def test_debit_keeps_concurrent_change(self):
        stale = Wallet.objects.get(user=self.user)
        Wallet.objects.filter(pk=stale.pk).update(balance=Decimal("60.00"))  # staff reduction lands

        services.debit(stale, Decimal("30.00"))

        self.assertEqual(balance_of(self.user), Decimal("30.00"))
        self.assertEqual(stale.balance, Decimal("30.00"))

    def test_credit_keeps_concurrent_change(self):
        stale = Wallet.objects.get(user=self.user)
        Wallet.objects.filter(pk=stale.pk).update(balance=Decimal("40.00"))  # withdrawal lands

        services.credit(stale, Decimal("500.00"))

        self.assertEqual(balance_of(self.user), Decimal("540.00"))

    def test_debit_checks_current_not_stale_balance(self):
        stale = Wallet.objects.get(user=self.user)
        Wallet.objects.filter(pk=stale.pk).update(balance=Decimal("10.00"))

        with self.assertRaises(services.InsufficientFunds):
            services.debit(stale, Decimal("50.00"))
        self.assertEqual(balance_of(self.user), Decimal("10.00"))


class AdminWalletAdjustmentTests(TestCase):
    """S13/N4/N5: staff adjustments are justified, referenced, audited and fraud-checked."""

    def setUp(self):
        self.user = make_user("owner@example.com", balance="100.00")
        self.staff = make_staff()
        self.client, _ = auth_client(self.staff)
        self.url = f"/wallets/admin/update/{Wallet.objects.get(user=self.user).pk}/"

    def adjust(self, balance, **overrides):
        payload = {"balance": balance, "reason": "Correct duplicate charge", "funding_reference": "ADJ-001", **overrides}
        payload = {k: v for k, v in payload.items() if v is not None}
        return self.client.patch(self.url, payload, format="json")

    def test_adjustment_writes_audit_record(self):
        res = self.adjust("40.00")

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["balance"], "40.00")
        self.assertEqual(balance_of(self.user), Decimal("40.00"))
        audit = Transaction.objects.get(sender=self.user)
        self.assertEqual((audit.transaction_type, audit.amount), ("withdraw", Decimal("60.00")))
        self.assertEqual(audit.created_by, self.staff)
        self.assertEqual(audit.funding_reference, "ADJ-001")
        self.assertIn("Correct duplicate charge", audit.description)

    def test_reason_and_reference_are_required(self):
        for missing in ("reason", "funding_reference"):
            with self.subTest(missing=missing):
                self.assertEqual(self.adjust("1000000.00", **{missing: None}).status_code, 400)
        self.assertEqual(balance_of(self.user), Decimal("100.00"))

    def test_reference_cannot_be_reused(self):
        self.adjust("150.00")
        res = self.adjust("900.00")

        self.assertEqual(res.status_code, 400)
        self.assertEqual(balance_of(self.user), Decimal("150.00"))

    def test_adjustment_is_fraud_checked(self):
        res = self.adjust("20000.00")

        self.assertEqual(res.status_code, 200)
        self.assertTrue(SuspiciousActivity.objects.filter(transaction__sender=self.user).exists())

    def test_failed_audit_rolls_back_balance(self):
        with patch("wallets.views.Transaction.objects.create", side_effect=RuntimeError("db down")):
            with self.assertRaises(RuntimeError):
                self.adjust("40.00")

        self.assertEqual(balance_of(self.user), Decimal("100.00"))

    def test_negative_balance_is_a_400(self):
        self.assertEqual(self.adjust("-1.00").status_code, 400)


@skipUnless(connection.vendor == "postgresql", "row locks need PostgreSQL; run with DATABASE_URL set")
class ConcurrentDebitTests(TransactionTestCase):
    """S4/S13 end to end: parallel debits can never overdraw or lose updates."""

    def test_parallel_withdrawals(self):
        user = make_user("racer@example.com", balance="100.00")
        barrier = threading.Barrier(5)
        results = []

        def withdraw():
            client, _ = auth_client(user)
            barrier.wait()
            results.append(
                client.post("/transactions/withdraw/", {"amount": "50.00"}, format="json").status_code
            )
            connection.close()

        threads = [threading.Thread(target=withdraw) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(sorted(results), [201, 201, 400, 400, 400])
        self.assertEqual(balance_of(user), Decimal("0.00"))


class NonPositiveAmountTests(TestCase):
    """N3: credit/debit refuse amounts that would flip their direction."""

    def test_credit_and_debit_reject_non_positive_amounts(self):
        user = make_user("user@example.com", balance="100.00")
        for func in (services.credit, services.debit):
            for amount in (Decimal("0"), Decimal("-50.00")):
                with self.subTest(func=func.__name__, amount=amount), self.assertRaises(ValueError):
                    with transaction.atomic():
                        (wallet,) = services.lock_wallets(user.pk)
                        func(wallet, amount)

        self.assertEqual(balance_of(user), Decimal("100.00"))

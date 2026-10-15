from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from loans.models import EMI, LoanApplication
from transactions.models import Transaction
from utils.testing import auth_client, balance_of, make_staff, make_user


class LoanApprovalTests(TestCase):
    """S4/S15: approval is a one-time, atomic state change."""

    def setUp(self):
        self.borrower = make_user("borrower@example.com")
        self.loan = LoanApplication.objects.create(
            user=self.borrower, amount=Decimal("1200.00"), duration_months=12
        )
        self.client, _ = auth_client(make_staff())

    def approve(self):
        return self.client.post(
            "/loans/admin/approve/", {"loan_id": self.loan.pk, "action": "approve"}, format="json"
        )

    def test_approval_credits_and_schedules(self):
        res = self.approve()

        self.assertEqual(res.status_code, 200)
        self.assertEqual(balance_of(self.borrower), Decimal("1200.00"))
        self.assertEqual(EMI.objects.filter(loan=self.loan).count(), 12)

    def test_second_approval_does_not_pay_out_again(self):
        self.approve()
        res = self.approve()

        self.assertEqual(res.status_code, 400)
        self.assertEqual(balance_of(self.borrower), Decimal("1200.00"))
        self.assertEqual(EMI.objects.filter(loan=self.loan).count(), 12)

    def test_rejected_loan_cannot_be_approved(self):
        self.client.post("/loans/admin/approve/", {"loan_id": self.loan.pk, "action": "reject"}, format="json")
        res = self.approve()

        self.assertEqual(res.status_code, 400)
        self.assertEqual(balance_of(self.borrower), Decimal("0.00"))


class EMIPayTests(TestCase):
    """S16: an EMI can only be paid once, even if two requests overlap."""

    def setUp(self):
        self.borrower = make_user("borrower@example.com", balance="500.00")
        loan = LoanApplication.objects.create(
            user=self.borrower, amount=Decimal("1000.00"), duration_months=10, status="approved"
        )
        self.emi = EMI.objects.create(loan=loan, due_date="2026-11-01", amount=Decimal("100.00"))
        self.client, _ = auth_client(self.borrower)
        self.url = f"/loans/emis/{self.emi.pk}/pay/"

    def test_pay_once(self):
        first = self.client.post(self.url)
        second = self.client.post(self.url)

        self.assertEqual((first.status_code, second.status_code), (200, 400))
        self.assertEqual(balance_of(self.borrower), Decimal("400.00"))

    def test_concurrent_payment_charges_once(self):
        from wallets import services

        real_lock = services.lock_wallets

        def other_request_wins(*user_ids):
            # The competing request marks the EMI paid after our is_paid read.
            EMI.objects.filter(pk=self.emi.pk).update(is_paid=True, paid_amount=Decimal("100.00"))
            return real_lock(*user_ids)

        with patch("loans.views.lock_wallets", side_effect=other_request_wins):
            res = self.client.post(self.url)

        self.assertEqual(res.status_code, 400)
        self.assertEqual(balance_of(self.borrower), Decimal("500.00"))

    def test_other_users_emi_is_not_found(self):
        client, _ = auth_client(make_user("stranger@example.com", balance="500.00"))

        self.assertEqual(client.post(self.url).status_code, 404)


class LoanLimitsTests(TestCase):
    """N3: loans can't be negative, zero, huge or unbounded in length."""

    def setUp(self):
        self.borrower = make_user("borrower@example.com", balance="100.00")
        self.client, _ = auth_client(self.borrower)

    def apply(self, amount, months=12):
        return self.client.post("/loans/apply/", {"amount": amount, "duration_months": months}, format="json")

    def test_out_of_range_applications_are_refused(self):
        for amount, months in [("-500.00", 12), ("0.00", 12), ("1000000.01", 12), ("100.00", 0), ("100.00", 61), ("100.00", 10**8)]:
            with self.subTest(amount=amount, months=months):
                self.assertEqual(self.apply(amount, months).status_code, 400)
        self.assertFalse(LoanApplication.objects.exists())

    def test_existing_negative_loan_cannot_be_approved(self):
        loan = LoanApplication.objects.create(user=self.borrower, amount=Decimal("-500.00"), duration_months=5)
        staff, _ = auth_client(make_staff())

        res = staff.post("/loans/admin/approve/", {"loan_id": loan.pk, "action": "approve"}, format="json")

        self.assertEqual(res.status_code, 400)
        self.assertEqual(balance_of(self.borrower), Decimal("100.00"))
        self.assertFalse(EMI.objects.filter(loan=loan).exists())

    def test_negative_emi_cannot_create_money(self):
        loan = LoanApplication.objects.create(user=self.borrower, amount=Decimal("-500.00"), duration_months=5, status="approved")
        emi = EMI.objects.create(loan=loan, due_date="2030-01-01", amount=Decimal("-100.00"))

        with self.assertRaises(ValueError):
            self.client.post(f"/loans/emis/{emi.pk}/pay/")

        self.assertEqual(balance_of(self.borrower), Decimal("100.00"))


class LoanGovernanceTests(TestCase):
    """N5/N8/N9: KYC to apply, decisions record who made them, no payout to closed accounts."""

    def setUp(self):
        self.borrower = make_user("borrower@example.com")
        self.staff = make_staff()
        self.staff_client, _ = auth_client(self.staff)

    def decide(self, loan, action="approve"):
        return self.staff_client.post("/loans/admin/approve/", {"loan_id": loan.pk, "action": action}, format="json")

    def test_unverified_customer_cannot_apply(self):
        client, _ = auth_client(make_user("new@example.com", kyc_status="pending"))
        res = client.post("/loans/apply/", {"amount": "100.00", "duration_months": 6}, format="json")

        self.assertEqual(res.status_code, 403)
        self.assertFalse(LoanApplication.objects.exists())

    def test_decisions_record_staff_member(self):
        approved = LoanApplication.objects.create(user=self.borrower, amount=Decimal("100.00"), duration_months=2)
        rejected = LoanApplication.objects.create(user=self.borrower, amount=Decimal("100.00"), duration_months=2)
        self.decide(approved)
        self.decide(rejected, "reject")

        for loan in (approved, rejected):
            loan.refresh_from_db()
            self.assertEqual(loan.decided_by, self.staff)
            self.assertIsNotNone(loan.decided_at)
        self.assertEqual(Transaction.objects.get(description__contains=f"Loan {approved.pk}").created_by, self.staff)

    def test_no_payout_to_account_closed_after_lookup(self):
        from users.models import User
        from wallets import services

        loan = LoanApplication.objects.create(user=self.borrower, amount=Decimal("100.00"), duration_months=2)

        def account_closes_first(*user_ids):
            User.objects.filter(pk=self.borrower.pk).update(is_active=False)
            return services.lock_wallets(*user_ids)

        with patch("loans.views.lock_wallets", side_effect=account_closes_first):
            res = self.decide(loan)

        self.assertEqual(res.status_code, 400)
        self.assertEqual(balance_of(self.borrower), Decimal("0.00"))
        loan.refresh_from_db()
        self.assertEqual(loan.status, "pending")


class LoanAdminInputTests(TestCase):
    """N15: malformed admin input is a 400, not a crash."""

    def test_non_numeric_loan_id(self):
        client, _ = auth_client(make_staff())

        res = client.post("/loans/admin/approve/", {"loan_id": "abc", "action": "approve"}, format="json")

        self.assertEqual(res.status_code, 400)

from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from loans.models import EMI, LoanApplication
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

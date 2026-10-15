"""Tests intentionally removed.

This file previously contained automated tests. The project has been
configured for manual testing via Postman/Swagger per developer request.
"""
# from django.test import TestCase
# from django.urls import reverse
# from rest_framework.test import APIClient
# from django.contrib.auth import get_user_model
# from transactions.models import Transaction
# from analytics.utils import simple_flagTransaction
# from decimal import Decimal

# User = get_user_model()

# class AnalyticsTests(TestCase):
#     def setUp(self):
#         self.client = APIClient()
#     self.alice = User.objects.create_user(username='alice_a@example.com', email='alice_a@example.com', first_name='A', last_name='A', password='pass')
#     self.bob = User.objects.create_user(username='bob_a@example.com', email='bob_a@example.com', first_name='B', last_name='B', password='pass')
#     self.admin = User.objects.create_superuser(username='admin_a@example.com', email='admin_a@example.com', first_name='Admin', last_name='A', password='admin')

#     def test_high_amount_flag(self):
#         tx = Transaction.objects.create(sender=self.alice, receiver=self.bob, transaction_type='transfer', amount=Decimal('20000'), status='successful')
#     sa = simple_flagTransaction(tx)
#     self.assertIsNotNone(sa)
#     self.assertIn('amount_exceeds_10000', getattr(sa, 'reason', ''))

#     def test_velocity_flag(self):
#         # create 3 recent transfers then a 4th should trigger velocity rule
#         """Tests intentionally removed.

#         This module previously contained automated tests. The project is now
#         configured for manual testing via Postman/Swagger per repository preference.
#         """
#     self.assertIn('high_transfer_velocity', getattr(sa, 'reason', ''))


from django.test import TestCase  # noqa: E402


class FlaggedFilterValidationTests(TestCase):
    """N15: bad report filters are a 400, not a crash or a silently ignored filter."""

    def test_bad_filters_are_rejected(self):
        from utils.testing import auth_client, make_staff

        client, _ = auth_client(make_staff())
        for params in ({"from_date": "not-a-date"}, {"to_date": "2026-13-45"}, {"risk_min": "high"}):
            with self.subTest(params=params):
                res = client.get("/analytics/flagged-transactions/", params)
                self.assertEqual(res.status_code, 400)
                self.assertIn(next(iter(params)), res.data)

    def test_good_filters_work(self):
        from utils.testing import auth_client, make_staff

        client, _ = auth_client(make_staff())
        res = client.get("/analytics/flagged-transactions/", {"from_date": "2026-01-01", "risk_min": "0.5"})

        self.assertEqual(res.status_code, 200)

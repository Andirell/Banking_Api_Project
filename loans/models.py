from decimal import Decimal

from django.conf import settings
from django.db import models


class LoanApplication(models.Model):
    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    )

    # PROTECT: a user with loans can never be deleted from the database
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="loan_applications")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    duration_months = models.IntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    reason = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Which staff member approved or rejected it, and when
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="decided_loans", null=True, blank=True
    )
    decided_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"Loan {self.id} - {self.user} - {self.status}"


class EMI(models.Model):
    # One monthly payment of a loan
    loan = models.ForeignKey(LoanApplication, on_delete=models.PROTECT, related_name="emis")
    due_date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    is_paid = models.BooleanField(default=False)

    def __str__(self):
        return f"EMI {self.id} for Loan {self.loan_id} - due {self.due_date}"

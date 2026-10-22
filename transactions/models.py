import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Transaction(models.Model):
    # Every change to a wallet balance creates one of these, so we always
    # have a full history of where money came from and went.

    TRANSACTION_TYPE_CHOICES = (
        ("deposit", "Deposit"),
        ("withdraw", "Withdraw"),
        ("transfer", "Transfer"),
    )

    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("successful", "Successful"),
        ("failed", "Failed"),
    )

    # A unique id we can show to customers, e.g. on a receipt
    reference = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    # PROTECT: transactions are never deleted, even if the account is closed
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sent_transactions"
    )
    receiver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="received_transactions",
        null=True,
        blank=True
    )

    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPE_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    description = models.TextField(blank=True, null=True)
    # For deposits: the bank/payment reference of the real money we received.
    # It is unique, so the same payment can't be used to credit a wallet twice.
    funding_reference = models.CharField(max_length=100, unique=True, blank=True, null=True)
    # The staff member who recorded it (empty for things customers did themselves)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recorded_transactions",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.transaction_type} - {self.amount} - {self.status}"

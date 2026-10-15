from decimal import Decimal

from rest_framework import serializers
from .models import LoanApplication, EMI
from users.models import User


class LoanApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoanApplication
        fields = ["id", "user", "amount", "duration_months", "status", "reason", "created_at"]
        read_only_fields = ["id", "user", "status", "created_at"]


MAX_LOAN_AMOUNT = Decimal("1000000.00")
MAX_LOAN_MONTHS = 60


class LoanApplyRequestSerializer(serializers.Serializer):
    # Bounded so an approval can never debit the wallet (negative amount) or
    # create an unbounded number of EMI rows (huge duration).
    amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.01"), max_value=MAX_LOAN_AMOUNT
    )
    duration_months = serializers.IntegerField(min_value=1, max_value=MAX_LOAN_MONTHS)
    reason = serializers.CharField(allow_blank=True, required=False)


class EMIReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = EMI
        fields = ["id", "loan", "due_date", "amount", "paid_amount", "is_paid"]

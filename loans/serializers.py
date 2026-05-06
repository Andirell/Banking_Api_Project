from rest_framework import serializers
from .models import LoanApplication, EMI
from users.models import User


class LoanApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoanApplication
        fields = ["id", "user", "amount", "duration_months", "status", "reason", "created_at"]
        read_only_fields = ["id", "user", "status", "created_at"]


class LoanApplyRequestSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    duration_months = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(allow_blank=True, required=False)


class EMIReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = EMI
        fields = ["id", "loan", "due_date", "amount", "paid_amount", "is_paid"]

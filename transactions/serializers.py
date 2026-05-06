from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Transaction

User = get_user_model()


class TransactionSerializer(serializers.ModelSerializer):
    sender = serializers.StringRelatedField()
    receiver = serializers.StringRelatedField()

    class Meta:
        model = Transaction
        fields = (
            "id",
            "reference",
            "sender",
            "receiver",
            "transaction_type",
            "amount",
            "status",
            "description",
            "created_at",
        )

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be greater than zero.")
        return value

class DepositSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    description = serializers.CharField(required=False, allow_blank=True)

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be greater than zero.")
        return value


class WithdrawSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    description = serializers.CharField(required=False, allow_blank=True)

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be greater than zero.")
        return value


class TransferSerializer(serializers.Serializer):
    receiver_email = serializers.EmailField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    description = serializers.CharField(required=False, allow_blank=True)

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be greater than zero.")
        return value

    def validate_receiver_email(self, value):
        request = self.context.get("request")

        try:
            receiver = User.objects.get(email=value)
        except User.DoesNotExist:
            raise serializers.ValidationError("Receiver with this email does not exist.")

        if request and request.user.email == value:
            raise serializers.ValidationError("You cannot transfer to yourself.")

        return value
from rest_framework import serializers

from .models import Transaction


def check_amount(value):
    if value <= 0:
        raise serializers.ValidationError("Amount must be greater than zero.")
    return value


class TransactionSerializer(serializers.ModelSerializer):
    # Show emails instead of user ids
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
        return check_amount(value)


class DepositSerializer(serializers.Serializer):
    """Staff-recorded deposit. The funding reference links it to the real payment."""

    user_id = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    funding_reference = serializers.CharField(max_length=100)
    description = serializers.CharField(required=False, allow_blank=True)

    def validate_amount(self, value):
        return check_amount(value)


class WithdrawSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    description = serializers.CharField(required=False, allow_blank=True)

    def validate_amount(self, value):
        return check_amount(value)


class TransferSerializer(serializers.Serializer):
    receiver_email = serializers.EmailField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    description = serializers.CharField(required=False, allow_blank=True)

    def validate_amount(self, value):
        return check_amount(value)

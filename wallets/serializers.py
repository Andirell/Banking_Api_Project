from decimal import Decimal

from rest_framework import serializers
from .models import Wallet
from users.models import User

class WalletSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(read_only=True)  # Display user's email instead of ID

    class Meta:
        model = Wallet
        # Balance is read-only for non-admin users; admins should use AdminWalletUpdateSerializer
        fields = ["user", "balance"]
        read_only_fields = ["balance"]


class AdminWalletUpdateSerializer(serializers.Serializer):
    """Staff balance correction. Like a deposit, it must be justified and referenced."""
    balance = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"))
    reason = serializers.CharField(max_length=255, write_only=True)
    funding_reference = serializers.CharField(max_length=100, write_only=True)

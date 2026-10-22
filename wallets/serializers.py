from decimal import Decimal

from rest_framework import serializers

from .models import Wallet


class WalletSerializer(serializers.ModelSerializer):
    # Show the user's email instead of their id
    user = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Wallet
        fields = ["user", "balance"]
        # Customers can never change their balance through this serializer
        read_only_fields = ["balance"]


class AdminWalletUpdateSerializer(serializers.Serializer):
    """Staff balance correction. Needs a reason and a unique reference."""

    balance = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"))
    reason = serializers.CharField(max_length=255, write_only=True)
    funding_reference = serializers.CharField(max_length=100, write_only=True)

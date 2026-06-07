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


class AdminWalletUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Wallet
        fields = ["balance"]

# Optionally, you can add validation for the balance field to prevent negative balance
    def validate_balance(self, value):
        if value < 0:
            raise serializers.ValidationError("Balance cannot be negative.")
        return value

# class UserSerializer(serializers.ModelSerializer):
#     class Meta:
#         model = User
#         fields = ['email']


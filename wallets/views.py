#from django.db import transaction as db_transaction
from asyncio.log import logger
import logging
from django.forms import ValidationError
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import NotFound

from users.views import ErrorResponse
from .models import Wallet
from .serializers import WalletSerializer, AdminWalletUpdateSerializer
from transactions.serializers import (DepositSerializer, WithdrawSerializer, TransferSerializer)
from rest_framework import serializers
from drf_spectacular.utils import extend_schema
from utils.schemas import WalletDetailResponse, WalletCreateResponse, WalletUpdateResponse, ErrorResponse
from rest_framework.permissions import IsAdminUser


# Swagger/OpenAPI Response Schemas

# Reuse wallet response shapes from utils.schemas


class WalletDetailAPIView(generics.RetrieveAPIView):
    queryset = Wallet.objects.all()
    serializer_class = WalletSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Retrieve wallet details",
        description="Retrieve the details of the authenticated user's wallet.",
        tags=["Wallets"],
        responses={200: WalletDetailResponse},  # Use the WalletDetailResponse schema
    )

    def get_object(self):
        # Use getattr to satisfy type checkers (AnonymousUser/AbstractUser may not have 'wallet')
        user = self.request.user
        wallet = getattr(user, "wallet", None)
        if wallet is None:
            raise NotFound("Wallet not found for the authenticated user")
        return wallet

class WalletCreateAPIView(generics.CreateAPIView):
    queryset = Wallet.objects.all()
    serializer_class = WalletSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Create a new wallet",
        description="Create a new wallet for the authenticated user.",
        tags=["Wallets"],
        responses={201: WalletCreateResponse},  # Use the WalletCreateResponse schema
    )

    def perform_create(self, serializer):
        # Prevent creating multiple wallets for the same user
        if hasattr(self.request.user, 'wallet'):
            raise ValidationError("User already has a wallet.")
        # Save wallet with initial zero balance; Decimal is used in model
        serializer.save(user=self.request.user, balance=0.00)

class WalletUpdateAPIView(generics.UpdateAPIView):
    queryset = Wallet.objects.all()
    serializer_class = WalletSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        user = self.request.user
        wallet = getattr(user, "wallet", None)
        if wallet is None:
            raise NotFound("Wallet not found for the authenticated user")
        return wallet  # Update the wallet of the authenticated user
    
    @extend_schema(
        summary="Update wallet balance",
        description="Update the balance of the authenticated user's wallet.",
        tags=["Wallets"],
        responses={200: WalletUpdateResponse},  # Use the WalletUpdateResponse schema
    )
     
    def perform_update(self, serializer):
        wallet = self.get_object()
        # Users should not be allowed to update balance directly.
        # Only admin endpoints should modify balance. If this view is used,
        # ignore any balance field and return the current wallet state.
        raise ValidationError("Users are not allowed to modify wallet balance. Use admin endpoints.")
    
class WalletAdminUpdateAPIView(generics.UpdateAPIView):
    """
    Admin can update the wallet balance for any user.
    """
    queryset = Wallet.objects.all()
    serializer_class = AdminWalletUpdateSerializer
    permission_classes = [IsAdminUser]  # Only admins can access this view

    @extend_schema(
        summary="Admin update wallet balance",
        description="This endpoint allows admins to update the wallet balance of any user. Admins can modify the balance directly, for example, adding or subtracting funds.",
        tags=["Wallets"],
        responses={
            200: WalletUpdateResponse,  # Custom Swagger response schema for success
            400: ErrorResponse,  # Schema for error responses (e.g., invalid input)
        },
        request=WalletSerializer,  # Define what the request body should look like
    )
   
    def perform_update(self, serializer):
        wallet = self.get_object()
        balance = serializer.validated_data.get("balance", wallet.balance)

        # Validate balance is not negative
        if balance < 0:
            raise ValidationError("Balance cannot be negative.")

        # Log the admin's action
        logger.info(f"Admin updated wallet balance for user {wallet.user.email} to {balance}")

        # Save change and create a Transaction audit record
        old_balance = wallet.balance
        wallet.balance = balance
        wallet.save(update_fields=["balance"])

        # Create a transaction record to represent the admin adjustment
        try:
            from transactions.models import Transaction
            Transaction.objects.create(
                sender=wallet.user,
                receiver=None,
                transaction_type='deposit' if balance > old_balance else 'withdraw',
                amount=abs(balance - old_balance),
                status='successful',
                description=f'Admin balance adjustment by {str(self.request.user)}'
            )
        except Exception:
            # Fail silently on audit creation to not block admin workflows
            logger.exception("Failed to create transaction audit record for admin wallet update")
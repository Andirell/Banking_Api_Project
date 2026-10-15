import logging
from django.db import IntegrityError, transaction as db_transaction
from rest_framework.exceptions import ValidationError
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
from transactions.models import Transaction
from analytics.utils import flag_transaction_safely
from .services import credit, debit, lock_wallets

logger = logging.getLogger(__name__)


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

    def get_serializer(self, *args, **kwargs):
        # PATCH would otherwise make reason and funding_reference optional.
        kwargs["partial"] = False
        return super().get_serializer(*args, **kwargs)

    @extend_schema(
        summary="Admin update wallet balance",
        description="Staff correction of a wallet balance. Requires a reason and a unique funding reference; the change is audited and fraud-checked.",
        tags=["Wallets"],
        responses={
            200: WalletUpdateResponse,  # Custom Swagger response schema for success
            400: ErrorResponse,  # Schema for error responses (e.g., invalid input)
        },
        request=AdminWalletUpdateSerializer,
    )
   
    def perform_update(self, serializer):
        wallet = serializer.instance
        validated = serializer.validated_data
        balance = validated["balance"]
        reference = validated["funding_reference"]

        # Lock the row so the old balance (and the audit amount) is the real
        # current value. The change, its audit record and the fraud check commit
        # together: if the audit can't be written, the balance change rolls back.
        try:
            with db_transaction.atomic():
                (locked,) = lock_wallets(wallet.user_id)
                old_balance = locked.balance
                if balance == old_balance:
                    return
                if balance > old_balance:
                    credit(locked, balance - old_balance)
                else:
                    debit(locked, old_balance - balance)

                tx = Transaction.objects.create(
                    sender=locked.user,
                    receiver=None,
                    transaction_type='deposit' if balance > old_balance else 'withdraw',
                    amount=abs(balance - old_balance),
                    status='successful',
                    funding_reference=reference,
                    created_by=self.request.user,
                    description=f'Admin balance adjustment: {validated["reason"]}',
                )
                flag_transaction_safely(tx)
        except IntegrityError:
            raise ValidationError({"funding_reference": "This funding reference has already been used."})

        logger.info("Admin %s set wallet %s balance %s -> %s", self.request.user.pk, wallet.pk, old_balance, balance)
        wallet.refresh_from_db(fields=["balance"])

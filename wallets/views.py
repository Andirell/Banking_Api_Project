import logging

from django.db import IntegrityError, transaction as db_transaction
from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAdminUser, IsAuthenticated

from analytics.utils import flag_transaction_safely
from transactions.models import Transaction
from utils.schemas import ErrorResponse, WalletCreateResponse, WalletDetailResponse, WalletUpdateResponse

from .models import Wallet
from .serializers import AdminWalletUpdateSerializer, WalletSerializer
from .services import credit, debit, lock_wallets

logger = logging.getLogger(__name__)


def get_my_wallet(user):
    wallet = getattr(user, "wallet", None)
    if wallet is None:
        raise NotFound("Wallet not found for the authenticated user")
    return wallet


class WalletDetailAPIView(generics.RetrieveAPIView):
    queryset = Wallet.objects.all()
    serializer_class = WalletSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Retrieve wallet details",
        description="Retrieve the details of the authenticated user's wallet.",
        tags=["Wallets"],
        responses={200: WalletDetailResponse},
    )
    def get_object(self):
        return get_my_wallet(self.request.user)


class WalletCreateAPIView(generics.CreateAPIView):
    queryset = Wallet.objects.all()
    serializer_class = WalletSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Create a new wallet",
        description="Create a new wallet for the authenticated user.",
        tags=["Wallets"],
        responses={201: WalletCreateResponse},
    )
    def perform_create(self, serializer):
        # Every user already gets a wallet when they sign up (see users/signals.py),
        # so this only matters for very old accounts.
        if hasattr(self.request.user, "wallet"):
            raise ValidationError("User already has a wallet.")
        serializer.save(user=self.request.user, balance=0.00)


class WalletUpdateAPIView(generics.UpdateAPIView):
    queryset = Wallet.objects.all()
    serializer_class = WalletSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return get_my_wallet(self.request.user)

    @extend_schema(
        summary="Update wallet balance",
        description="Update the balance of the authenticated user's wallet.",
        tags=["Wallets"],
        responses={200: WalletUpdateResponse},
    )
    def perform_update(self, serializer):
        # Customers are never allowed to set their own balance.
        raise ValidationError("Users are not allowed to modify wallet balance. Use admin endpoints.")


class WalletAdminUpdateAPIView(generics.UpdateAPIView):
    """Admin can update the wallet balance for any user."""

    # The change is saved as a transaction so there is always a record of
    # who changed what and why.
    queryset = Wallet.objects.all()
    serializer_class = AdminWalletUpdateSerializer
    permission_classes = [IsAdminUser]

    def get_serializer(self, *args, **kwargs):
        # PATCH normally makes every field optional. Here the reason and
        # reference are always required, so we turn that off.
        kwargs["partial"] = False
        return super().get_serializer(*args, **kwargs)

    @extend_schema(
        summary="Admin update wallet balance",
        description="Staff correction of a wallet balance. Requires a reason and a unique funding reference; the change is audited and fraud-checked.",
        tags=["Wallets"],
        responses={200: WalletUpdateResponse, 400: ErrorResponse},
        request=AdminWalletUpdateSerializer,
    )
    def perform_update(self, serializer):
        wallet = serializer.instance
        new_balance = serializer.validated_data["balance"]
        reference = serializer.validated_data["funding_reference"]
        reason = serializer.validated_data["reason"]

        try:
            # Everything below is saved together. If the transaction record
            # can't be saved, the balance change is undone too.
            with db_transaction.atomic():
                # Lock the wallet so we work with its real current balance
                (locked_wallet,) = lock_wallets(wallet.user_id)
                old_balance = locked_wallet.balance

                if new_balance == old_balance:
                    return

                if new_balance > old_balance:
                    difference = new_balance - old_balance
                    credit(locked_wallet, difference)
                    transaction_type = "deposit"
                else:
                    difference = old_balance - new_balance
                    debit(locked_wallet, difference)
                    transaction_type = "withdraw"

                tx = Transaction.objects.create(
                    sender=locked_wallet.user,
                    receiver=None,
                    transaction_type=transaction_type,
                    amount=difference,
                    status="successful",
                    funding_reference=reference,
                    created_by=self.request.user,
                    description=f"Admin balance adjustment: {reason}",
                )
                flag_transaction_safely(tx)
        except IntegrityError:
            # funding_reference is unique in the database
            raise ValidationError({"funding_reference": "This funding reference has already been used."})

        logger.info("Admin %s set wallet %s balance %s -> %s", self.request.user.pk, wallet.pk, old_balance, new_balance)
        wallet.refresh_from_db(fields=["balance"])

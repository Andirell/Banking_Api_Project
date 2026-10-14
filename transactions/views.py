from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework import status, generics
from rest_framework.viewsets import ReadOnlyModelViewSet
from django.db import IntegrityError, transaction as db_transaction
from users.models import User
from decimal import Decimal
from typing import Any, Dict, cast, TYPE_CHECKING

if TYPE_CHECKING:
    from django.db.models import Model
from .models import Transaction
from .serializers import DepositSerializer, WithdrawSerializer, TransferSerializer, TransactionSerializer
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from utils.schemas import TransactionActionResponse, ErrorResponse, ValidationErrorResponse
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from analytics.utils import flag_transaction_safely
from wallets.services import InsufficientFunds, credit, debit, lock_wallets
import logging
logger = logging.getLogger(__name__)  # Set up logging

class DepositAPIView(APIView):
    # Customers can't credit themselves: a deposit is staff recording money that
    # actually arrived, identified by a funding reference that can't be reused.
    permission_classes = [IsAdminUser]

    @extend_schema(
        summary="Record a deposit (staff)",
        description="Credit a user's wallet for funds received externally. Requires a unique funding reference.",
        tags=["Transactions"],
        request=DepositSerializer,
        responses={
            201: TransactionActionResponse,
            400: ValidationErrorResponse,
            409: ErrorResponse,
        },
    )
    def post(self, request):
        serializer = DepositSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated: Dict[str, Any] = cast(Dict[str, Any], serializer.validated_data)

        amount: Decimal = validated["amount"]
        reference: str = validated["funding_reference"]
        owner = User.objects.filter(pk=validated["user_id"], is_active=True).first()
        if owner is None:
            return Response({"error": "User not found."}, status=status.HTTP_400_BAD_REQUEST)

        if Transaction.objects.filter(funding_reference=reference).exists():
            return Response({"error": "This funding reference has already been used."}, status=status.HTTP_409_CONFLICT)

        try:
            with db_transaction.atomic():
                (wallet,) = lock_wallets(owner.pk)
                credit(wallet, amount)
                transaction_obj = Transaction.objects.create(
                    sender=owner,
                    receiver=None,
                    transaction_type="deposit",
                    amount=amount,
                    status="successful",
                    funding_reference=reference,
                    description=validated.get("description") or f"Deposit recorded by {request.user}",
                )
                flag_transaction_safely(transaction_obj)
        except IntegrityError:
            # Lost a race with another request using the same reference; nothing was credited.
            return Response({"error": "This funding reference has already been used."}, status=status.HTTP_409_CONFLICT)

        return Response(
            {
                "message": "Deposit successful",
                "balance": wallet.balance,
                "transaction": TransactionSerializer(transaction_obj).data,
            },
            status=status.HTTP_201_CREATED,
        )

# 2. Withdraw View
class WithdrawAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Withdraw money",
        description="Withdraw money from the authenticated user's balance.",
        tags=["Transactions"],
        request=WithdrawSerializer,
        responses={
            201: TransactionActionResponse,
            400: ErrorResponse,
        },
    )
    def post(self, request):
        serializer = WithdrawSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated: Dict[str, Any] = cast(Dict[str, Any], serializer.validated_data)

        amount: Decimal = validated["amount"]
        description: str = validated.get("description", "")

        with db_transaction.atomic():
            (wallet,) = lock_wallets(request.user.pk)
            try:
                debit(wallet, amount)
            except InsufficientFunds:
                return Response({"error": "Insufficient funds."}, status=status.HTTP_400_BAD_REQUEST)

            transaction_obj = Transaction.objects.create(
                sender=request.user,
                receiver=None,
                transaction_type="withdraw",
                amount=amount,
                status="successful",
                description=description,
            )
            flag_transaction_safely(transaction_obj)

        return Response(
            {
                "message": "Withdrawal successful",
                "balance": wallet.balance,
                "transaction": TransactionSerializer(transaction_obj).data,
            },
            status=status.HTTP_201_CREATED,
        )




class TransferAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Transfer money",
        description="Transfer money from the authenticated user to another user by email.",
        tags=["Transactions"],
        request=TransferSerializer,
        responses={
            201: TransactionActionResponse,
            400: ErrorResponse,
        },
    )
    def post(self, request):
        serializer = TransferSerializer(data=request.data, context={"request": request})

        if not serializer.is_valid():
            return Response({"errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        validated = serializer.validated_data
        amount = validated["amount"]
        description = validated.get("description", "")

        receiver = User.objects.filter(email=validated["receiver_email"], is_active=True).first()
        if receiver is None:
            return Response({"error": "Receiver not found."}, status=status.HTTP_400_BAD_REQUEST)
        if receiver.pk == request.user.pk:
            return Response({"error": "You cannot transfer to yourself."}, status=status.HTTP_400_BAD_REQUEST)

        with db_transaction.atomic():
            sender_wallet, receiver_wallet = lock_wallets(request.user.pk, receiver.pk)
            try:
                debit(sender_wallet, amount)
            except InsufficientFunds:
                return Response({"error": "Insufficient funds."}, status=status.HTTP_400_BAD_REQUEST)
            credit(receiver_wallet, amount)

            transaction_obj = Transaction.objects.create(
                sender=request.user,
                receiver=receiver,
                transaction_type="transfer",
                amount=amount,
                status="successful",
                description=description,
            )
            flag_transaction_safely(transaction_obj)

        logger.info("Transfer %s: %s -> %s, amount %s", transaction_obj.reference, request.user.pk, receiver.pk, amount)
        return Response(
            {
                "message": "Transfer successful",
                "balance": sender_wallet.balance,
                "transaction": TransactionSerializer(transaction_obj).data,
            },
            status=status.HTTP_201_CREATED,
        )


# 4. Transaction History View
class TransactionHistoryAPIView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TransactionSerializer

    def get_queryset(self):
        user = self.request.user
        return Transaction.objects.filter(sender=user).order_by('-created_at')

# 5. Transaction Detail View
class TransactionDetailAPIView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TransactionSerializer

    def get_object(self):
        try:
            transaction_obj = Transaction.objects.get(id=self.kwargs["pk"], sender=self.request.user)
        except Transaction.DoesNotExist:
            raise NotFound("Transaction not found or you don't have access to this transaction.")

        return transaction_obj

    def get(self, request, *args, **kwargs):
        transaction_obj = self.get_object()

        return Response(
            {
                "message": "Transaction retrieved successfully",
                "data": TransactionSerializer(transaction_obj).data,
            },
            status=status.HTTP_200_OK,
        )


# ViewSet to expose list and retrieve under a single resource path
@extend_schema_view(
    retrieve=extend_schema(
        parameters=[
            OpenApiParameter(name="pk", description="Transaction ID", required=True, type=OpenApiTypes.INT),
            # Some routers or tooling may present the path parameter as 'id' instead of 'pk'.
            # Include both names so the schema generator can infer the correct integer type.
            OpenApiParameter(name="id", description="Transaction ID", required=True, type=OpenApiTypes.INT),
        ]
    )
)
class TransactionViewSet(ReadOnlyModelViewSet):
    """Provides list and retrieve endpoints for the authenticated user's transactions.

    Using a ViewSet + router groups the list and retrieve operations under the
    same base path (e.g. /transactions/ and /transactions/{pk}/), which makes
    the OpenAPI docs render them together as one resource.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = TransactionSerializer
    # Provide a queryset attribute so drf-spectacular can inspect the model
    # and correctly infer types for path parameters. We still restrict the
    # actual returned queryset in get_queryset() to the requesting user.
    queryset = Transaction.objects.all()

    lookup_field = "pk"

    def get_queryset(self):
        user = self.request.user
        return Transaction.objects.filter(sender=user).order_by('-created_at')
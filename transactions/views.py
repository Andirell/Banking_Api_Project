from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status, generics
from rest_framework.viewsets import ReadOnlyModelViewSet
from django.db import transaction as db_transaction
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
from analytics.utils import simple_flagTransaction
import logging
logger = logging.getLogger(__name__)  # Set up logging

class DepositAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Deposit money",
        description="Deposit money into the authenticated user's balance.",
        tags=["Transactions"],
        request=DepositSerializer,
        responses={
            201: TransactionActionResponse,
            400: ValidationErrorResponse,
        },
    )
    def post(self, request):
        serializer = DepositSerializer(data=request.data)
        # validate and raise a proper exception for invalid input
        serializer.is_valid(raise_exception=True)
        validated: Dict[str, Any] = cast(Dict[str, Any], serializer.validated_data)

        amount: Decimal = validated["amount"]
        description: str = validated.get("description", "")

        if amount <= 0:
            return Response({"error": "Amount must be greater than zero."}, status=status.HTTP_400_BAD_REQUEST)

        with db_transaction.atomic():
            user = User.objects.select_for_update().get(pk=request.user.pk)

            wallet = user.wallet  # type: ignore
            wallet.balance += amount
            wallet.save(update_fields=["balance"])

            transaction_obj = Transaction.objects.create(
                sender=user,
                receiver=None,
                transaction_type="deposit",
                amount=amount,
                status="successful",
                description=description,
            )

            # Run a simple fraud detector and persist any flagged activity
            try:
                simple_flagTransaction(transaction_obj)
            except Exception:
                # don't let analytics failures interrupt transactions
                pass

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

        if amount <= 0:
            return Response({"error": "Amount must be greater than zero."}, status=status.HTTP_400_BAD_REQUEST)

        # We use an atomic block to ensure the balance check and update are
        # performed together. `select_for_update()` locks the user row until
        # the transaction completes so concurrent withdrawals don't corrupt the balance.
        with db_transaction.atomic():
            user = User.objects.select_for_update().get(pk=request.user.pk)

            wallet = user.wallet  # type: ignore
            if wallet.balance < amount:
                return Response({"error": "Insufficient funds."}, status=status.HTTP_400_BAD_REQUEST)

        
            wallet.balance -= amount
            wallet.save(update_fields=["balance"])

            transaction_obj = Transaction.objects.create(
                sender=user,
                receiver=None,
                transaction_type="withdraw",
                amount=amount,
                status="successful",
                description=description,
            )

            try:
                simple_flagTransaction(transaction_obj)
            except Exception:
                pass

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
        
        # Check if serializer is valid
        if not serializer.is_valid():
            logger.error(f"TransferSerializer errors: {serializer.errors}")
            return Response({"errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        
        validated = serializer.validated_data
        receiver_email = validated["receiver_email"]
        amount = validated["amount"]
        description = validated.get("description", "")

        # Ensure the transfer amount is greater than zero
        if amount <= 0:
            logger.error(f"Invalid transfer amount: {amount}")
            return Response({"error": "Amount must be greater than zero."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with db_transaction.atomic():
                # Lock both sender and receiver to avoid race conditions
                sender = User.objects.select_for_update().get(pk=request.user.pk)
                receiver = User.objects.select_for_update().get(email=receiver_email)

                # Log sender and receiver details
                logger.info(f"Sender: {sender.email}, Receiver: {receiver.email}, Amount: {amount}")

                # Prevent sender from transferring to themselves
                if sender.id == receiver.id:
                    logger.error(f"Sender cannot transfer to themselves. Sender ID: {sender.id} - Receiver ID: {receiver.id}")
                    return Response({"error": "You cannot transfer to yourself."}, status=status.HTTP_400_BAD_REQUEST)

                # Check if sender has enough funds
                if sender.wallet.balance < amount:
                    logger.error(f"Insufficient funds: {sender.wallet.balance} < {amount}")
                    return Response({"error": "Insufficient funds."}, status=status.HTTP_400_BAD_REQUEST)

                # Update sender and receiver wallets
                sender.wallet.balance -= amount
                receiver.wallet.balance += amount

                # Save the updated wallet balances
                sender.wallet.save(update_fields=["balance"])
                receiver.wallet.save(update_fields=["balance"])

                # Create transaction record
                transaction_obj = Transaction.objects.create(
                    sender=sender,
                    receiver=receiver,
                    transaction_type="transfer",
                    amount=amount,
                    status="successful",
                    description=description,
                )

                logger.info(f"Transaction created: {transaction_obj.id}, Amount: {amount}, Status: {transaction_obj.status}")

                return Response(
                    {
                        "message": "Transfer successful",
                        "balance": sender.wallet.balance,
                        "transaction": TransactionSerializer(transaction_obj).data,
                    },
                    status=status.HTTP_201_CREATED,
                )
        except Exception as e:
            logger.error(f"Error during transfer: {str(e)}")
            return Response({"error": "Internal Server Error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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
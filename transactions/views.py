import logging

from django.conf import settings
from django.db import IntegrityError, transaction as db_transaction
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView
from rest_framework.viewsets import ReadOnlyModelViewSet

from analytics.utils import flag_transaction_safely
from users.models import User
from users.permissions import IsKYCVerified
from utils.schemas import ErrorResponse, TransactionActionResponse, ValidationErrorResponse
from wallets.services import InsufficientFunds, credit, debit, lock_wallets

from .models import Transaction
from .serializers import DepositSerializer, TransactionSerializer, TransferSerializer, WithdrawSerializer

logger = logging.getLogger(__name__)

DUPLICATE_REFERENCE_ERROR = "This funding reference has already been used."

# We give the same error whether the receiver doesn't exist, is closed or is
# blocked. Otherwise people could use transfers to check which emails have accounts.
RECEIVER_ERROR = "Transfer could not be completed. Check the receiver's email."


def is_active_user(user_id):
    return User.objects.filter(pk=user_id, is_active=True).exists()


class DepositAPIView(APIView):
    # Staff only. Customers can't add money to their own wallet. A deposit is
    # staff recording that real money arrived, with a reference that can only
    # be used once.
    permission_classes = [IsAdminUser]

    @extend_schema(
        summary="Record a deposit (staff)",
        description="Credit a user's wallet for funds received externally. Requires a unique funding reference.",
        tags=["Transactions"],
        request=DepositSerializer,
        responses={201: TransactionActionResponse, 400: ValidationErrorResponse, 409: ErrorResponse},
    )
    def post(self, request):
        serializer = DepositSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        amount = data["amount"]
        reference = data["funding_reference"]

        owner = User.objects.filter(pk=data["user_id"], is_active=True).first()
        if owner is None:
            return Response({"error": "User not found."}, status=status.HTTP_400_BAD_REQUEST)

        if Transaction.objects.filter(funding_reference=reference).exists():
            return Response({"error": DUPLICATE_REFERENCE_ERROR}, status=status.HTTP_409_CONFLICT)

        try:
            with db_transaction.atomic():
                (wallet,) = lock_wallets(owner.pk)

                # Check again now that the wallet is locked: the account
                # might have been closed in the meantime
                if not is_active_user(owner.pk):
                    return Response({"error": "User not found."}, status=status.HTTP_400_BAD_REQUEST)

                credit(wallet, amount)
                transaction_obj = Transaction.objects.create(
                    sender=owner,
                    receiver=None,
                    transaction_type="deposit",
                    amount=amount,
                    status="successful",
                    funding_reference=reference,
                    created_by=request.user,
                    description=data.get("description") or f"Deposit recorded by {request.user}",
                )
                flag_transaction_safely(transaction_obj)
        except IntegrityError:
            # Another request used the same reference at the same moment.
            # The database refused ours, so nothing was credited.
            return Response({"error": DUPLICATE_REFERENCE_ERROR}, status=status.HTTP_409_CONFLICT)

        return Response(
            {
                "message": "Deposit successful",
                "balance": wallet.balance,
                "transaction": TransactionSerializer(transaction_obj).data,
            },
            status=status.HTTP_201_CREATED,
        )


class WithdrawAPIView(APIView):
    # Taking money out needs verified KYC
    permission_classes = [IsAuthenticated, IsKYCVerified]

    @extend_schema(
        summary="Withdraw money",
        description="Withdraw money from the authenticated user's balance.",
        tags=["Transactions"],
        request=WithdrawSerializer,
        responses={201: TransactionActionResponse, 400: ErrorResponse},
    )
    def post(self, request):
        serializer = WithdrawSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        amount = serializer.validated_data["amount"]
        description = serializer.validated_data.get("description", "")

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


class TransferRateThrottle(UserRateThrottle):
    # Limits how many transfers one user can make (rate is in settings.py)
    scope = "transfer"


class TransferAPIView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [TransferRateThrottle]

    @extend_schema(
        summary="Transfer money",
        description="Transfer money from the authenticated user to another user by email.",
        tags=["Transactions"],
        request=TransferSerializer,
        responses={201: TransactionActionResponse, 400: ErrorResponse},
    )
    def post(self, request):
        serializer = TransferSerializer(data=request.data, context={"request": request})
        if not serializer.is_valid():
            return Response({"errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        amount = serializer.validated_data["amount"]
        description = serializer.validated_data.get("description", "")
        receiver_email = serializer.validated_data["receiver_email"]

        # Users without verified KYC can only send small amounts
        limit = settings.UNVERIFIED_TRANSFER_LIMIT
        if amount > limit and request.user.kyc_status != "verified":
            return Response(
                {"error": f"Complete KYC verification to send more than {limit}."},
                status=status.HTTP_403_FORBIDDEN,
            )

        receiver = User.objects.filter(email__iexact=receiver_email, is_active=True).first()
        if receiver is None:
            return Response({"error": RECEIVER_ERROR}, status=status.HTTP_400_BAD_REQUEST)
        if receiver.pk == request.user.pk:
            return Response({"error": "You cannot transfer to yourself."}, status=status.HTTP_400_BAD_REQUEST)

        with db_transaction.atomic():
            sender_wallet, receiver_wallet = lock_wallets(request.user.pk, receiver.pk)

            # Check again now that the wallets are locked: the receiver
            # might have closed their account in the meantime
            if not is_active_user(receiver.pk):
                return Response({"error": RECEIVER_ERROR}, status=status.HTTP_400_BAD_REQUEST)

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


@extend_schema_view(
    retrieve=extend_schema(
        parameters=[
            OpenApiParameter(name="pk", description="Transaction ID", required=True, type=OpenApiTypes.INT),
            OpenApiParameter(name="id", description="Transaction ID", required=True, type=OpenApiTypes.INT),
        ]
    )
)
class TransactionViewSet(ReadOnlyModelViewSet):
    """List or view the authenticated user's own transactions."""

    permission_classes = [IsAuthenticated]
    serializer_class = TransactionSerializer
    # Only here so the Swagger docs know the model. get_queryset() below is
    # what actually decides what the user can see.
    queryset = Transaction.objects.all()
    lookup_field = "pk"

    def get_queryset(self):
        return Transaction.objects.filter(sender=self.request.user).order_by("-created_at")

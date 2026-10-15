"""Loan endpoints

This module contains simple endpoints for applying for a loan, checking loan
status, and admin approval. The approval flow credits the user's wallet and
creates a simple EMI schedule. This is intentionally simple for learning.
"""

from rest_framework import generics, permissions, status, serializers
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from django.shortcuts import get_object_or_404
from .models import LoanApplication
from .serializers import MAX_LOAN_AMOUNT, MAX_LOAN_MONTHS, LoanApplicationSerializer, LoanApplyRequestSerializer
from users.models import User
from users.permissions import IsKYCVerified
from wallets.services import InsufficientFunds, credit, debit, lock_wallets
from .utils import create_emis_for_loan
from rest_framework.views import APIView
from .models import EMI
from .serializers import EMIReadSerializer
from django.db import transaction as db_transaction
from django.db.models import F
from django.utils import timezone
from transactions.models import Transaction
from decimal import Decimal
from drf_spectacular.utils import extend_schema
from drf_spectacular.types import OpenApiTypes
from utils.schemas import ErrorResponse


# Small serializers used for schema generation only
class AdminApproveRequestSerializer(serializers.Serializer):
    loan_id = serializers.IntegerField()
    action = serializers.ChoiceField(choices=("approve", "reject"))


class EMIPayResponseSerializer(serializers.Serializer):
    emi_id = serializers.IntegerField()
    loan_id = serializers.IntegerField(allow_null=True)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    transaction_reference = serializers.CharField()


class LoanApplyAPIView(generics.CreateAPIView):
    serializer_class = LoanApplyRequestSerializer
    permission_classes = [permissions.IsAuthenticated, IsKYCVerified]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Create a LoanApplication with status 'pending'. An admin will later
        # approve or reject the request.
        loan = LoanApplication.objects.create(
            user=request.user,
            amount=serializer.validated_data["amount"],
            duration_months=serializer.validated_data["duration_months"],
            reason=serializer.validated_data.get("reason", ""),
            status="pending",
        )
        return Response(LoanApplicationSerializer(loan).data, status=status.HTTP_201_CREATED)


class LoanStatusAPIView(generics.RetrieveAPIView):
    serializer_class = LoanApplicationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return get_object_or_404(LoanApplication, pk=self.kwargs["pk"], user=self.request.user)


@extend_schema(request=AdminApproveRequestSerializer, responses={200: OpenApiTypes.OBJECT, 400: ErrorResponse})
@api_view(["POST"])
@permission_classes([permissions.IsAdminUser])
def admin_approve_loan(request):
    request_serializer = AdminApproveRequestSerializer(data=request.data)
    if not request_serializer.is_valid():
        return Response({"error": "loan_id (integer) and action (approve/reject) are required"}, status=status.HTTP_400_BAD_REQUEST)
    loan_id = request_serializer.validated_data["loan_id"]
    action = request_serializer.validated_data["action"]

    # One atomic unit: decision, disbursement, ledger entry and schedule. The
    # loan row is locked so two approvals can't both see "pending".
    with db_transaction.atomic():
        loan = get_object_or_404(LoanApplication.objects.select_for_update(), pk=loan_id)
        if loan.status != "pending":
            return Response({"error": f"loan is already {loan.status}"}, status=status.HTTP_400_BAD_REQUEST)

        if action == "approve":
            # Applications from before the apply-time limits existed may be out of range.
            if not (0 < loan.amount <= MAX_LOAN_AMOUNT and 1 <= loan.duration_months <= MAX_LOAN_MONTHS):
                return Response({"error": "loan amount or duration is out of range"}, status=status.HTTP_400_BAD_REQUEST)
            (wallet,) = lock_wallets(loan.user_id)
            # Checked under the wallet lock that account closure also takes.
            if not User.objects.filter(pk=loan.user_id, is_active=True).exists():
                return Response({"error": "borrower's account is closed or blocked"}, status=status.HTTP_400_BAD_REQUEST)
            loan.status = "approved"
            loan.decided_by = request.user
            loan.decided_at = timezone.now()
            loan.save(update_fields=["status", "decided_by", "decided_at"])

            credit(wallet, loan.amount)
            Transaction.objects.create(
                sender=loan.user,
                receiver=None,
                transaction_type="deposit",
                amount=loan.amount,
                status="successful",
                created_by=request.user,
                description=f"Loan {loan.pk} disbursement",
            )
            create_emis_for_loan(loan)
        else:
            loan.status = "rejected"
            loan.decided_by = request.user
            loan.decided_at = timezone.now()
            loan.save(update_fields=["status", "decided_by", "decided_at"])

    return Response({"message": f"loan {action}d"}, status=status.HTTP_200_OK)


class AdminLoanListAPIView(generics.ListAPIView):
    permission_classes = [permissions.IsAdminUser]
    serializer_class = LoanApplicationSerializer

    def get_queryset(self):
        return LoanApplication.objects.all().order_by('-created_at')


class EMIListAPIView(generics.ListAPIView):
    """List unpaid EMIs for the authenticated user."""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EMIReadSerializer

    def get_queryset(self):
        return EMI.objects.filter(loan__user=self.request.user, is_paid=False).order_by('due_date')


class EMIPayAPIView(APIView):
    """Pay a single EMI from the authenticated user's wallet.

    POST /loans/emis/{emi_id}/pay/
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses={200: EMIPayResponseSerializer, 400: ErrorResponse})
    def post(self, request, emi_id):
        # Scoping the lookup to the owner means other users' EMIs are simply not found.
        emi = get_object_or_404(EMI.objects.select_related("loan"), pk=emi_id, loan__user=request.user)

        if emi.is_paid:
            return Response({"detail": "EMI already paid."}, status=status.HTTP_400_BAD_REQUEST)

        with db_transaction.atomic():
            (wallet,) = lock_wallets(request.user.pk)

            # Re-check in the same statement that marks it paid: the is_paid read
            # above may already be stale if another payment request won.
            marked = EMI.objects.filter(pk=emi.pk, is_paid=False).update(is_paid=True, paid_amount=F("amount"))
            if not marked:
                return Response({"detail": "EMI already paid."}, status=status.HTTP_400_BAD_REQUEST)

            try:
                debit(wallet, emi.amount)
            except InsufficientFunds:
                db_transaction.set_rollback(True)  # undo marking the EMI paid
                return Response({"detail": "Insufficient funds."}, status=status.HTTP_400_BAD_REQUEST)

            # create a transaction record for bookkeeping
            loan_id_val = getattr(getattr(emi, 'loan', None), 'id', None)
            emi_id_val = getattr(emi, 'id', None)
            tx = Transaction.objects.create(
                sender=request.user,
                receiver=None,
                transaction_type='withdraw',
                amount=emi.amount,
                status='successful',
                description=f'EMI payment for loan {loan_id_val} EMI {emi_id_val}'
            )

        return Response({
            "emi_id": emi_id_val,
            "loan_id": loan_id_val,
            "amount": str(emi.amount),
            "transaction_reference": str(tx.reference),
        }, status=status.HTTP_200_OK)


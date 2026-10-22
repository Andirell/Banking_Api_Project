"""Loan endpoints.

Customers apply for a loan, staff approve or reject it, and once approved the
money goes into the customer's wallet and a monthly payment plan (EMIs) is made.
"""

from django.db import transaction as db_transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions, serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView

from transactions.models import Transaction
from users.models import User
from users.permissions import IsKYCVerified
from utils.schemas import ErrorResponse
from wallets.services import InsufficientFunds, credit, debit, lock_wallets

from .models import EMI, LoanApplication
from .serializers import (
    MAX_LOAN_AMOUNT,
    MAX_LOAN_MONTHS,
    EMIReadSerializer,
    LoanApplicationSerializer,
    LoanApplyRequestSerializer,
)
from .utils import create_emis_for_loan


# These two serializers are only used for the Swagger docs
class AdminApproveRequestSerializer(serializers.Serializer):
    loan_id = serializers.IntegerField()
    action = serializers.ChoiceField(choices=("approve", "reject"))


class EMIPayResponseSerializer(serializers.Serializer):
    emi_id = serializers.IntegerField()
    loan_id = serializers.IntegerField(allow_null=True)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    transaction_reference = serializers.CharField()


class LoanApplyAPIView(generics.CreateAPIView):
    # Only customers with verified KYC can apply
    serializer_class = LoanApplyRequestSerializer
    permission_classes = [permissions.IsAuthenticated, IsKYCVerified]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # The loan starts as "pending" until a staff member decides
        loan = LoanApplication.objects.create(
            user=request.user,
            amount=data["amount"],
            duration_months=data["duration_months"],
            reason=data.get("reason", ""),
            status="pending",
        )
        return Response(LoanApplicationSerializer(loan).data, status=status.HTTP_201_CREATED)


class LoanStatusAPIView(generics.RetrieveAPIView):
    serializer_class = LoanApplicationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        # Filtering by user means you can only see your own loans
        return get_object_or_404(LoanApplication, pk=self.kwargs["pk"], user=self.request.user)


def mark_loan_decided(loan, new_status, staff_user):
    loan.status = new_status
    loan.decided_by = staff_user
    loan.decided_at = timezone.now()
    loan.save(update_fields=["status", "decided_by", "decided_at"])


@extend_schema(request=AdminApproveRequestSerializer, responses={200: OpenApiTypes.OBJECT, 400: ErrorResponse})
@api_view(["POST"])
@permission_classes([permissions.IsAdminUser])
def admin_approve_loan(request):
    request_serializer = AdminApproveRequestSerializer(data=request.data)
    if not request_serializer.is_valid():
        return Response(
            {"error": "loan_id (integer) and action (approve/reject) are required"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    loan_id = request_serializer.validated_data["loan_id"]
    action = request_serializer.validated_data["action"]

    # Everything in here is saved together or not at all: the decision,
    # the money, the transaction record and the payment plan.
    with db_transaction.atomic():
        # select_for_update locks the loan row. If two staff members click
        # "approve" at the same time, the second one waits and then sees
        # that the loan is no longer pending.
        loan = get_object_or_404(LoanApplication.objects.select_for_update(), pk=loan_id)
        if loan.status != "pending":
            return Response({"error": f"loan is already {loan.status}"}, status=status.HTTP_400_BAD_REQUEST)

        if action == "reject":
            mark_loan_decided(loan, "rejected", request.user)
            return Response({"message": "loan rejected"}, status=status.HTTP_200_OK)

        # Old applications (from before we added limits) might be out of range
        amount_ok = 0 < loan.amount <= MAX_LOAN_AMOUNT
        months_ok = 1 <= loan.duration_months <= MAX_LOAN_MONTHS
        if not amount_ok or not months_ok:
            return Response({"error": "loan amount or duration is out of range"}, status=status.HTTP_400_BAD_REQUEST)

        (wallet,) = lock_wallets(loan.user_id)

        # Check this after locking the wallet, because closing an account
        # takes the same lock (see users/views.py delete_user)
        if not User.objects.filter(pk=loan.user_id, is_active=True).exists():
            return Response({"error": "borrower's account is closed or blocked"}, status=status.HTTP_400_BAD_REQUEST)

        mark_loan_decided(loan, "approved", request.user)

        # Pay the loan into the customer's wallet
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

    return Response({"message": "loan approved"}, status=status.HTTP_200_OK)


class AdminLoanListAPIView(generics.ListAPIView):
    permission_classes = [permissions.IsAdminUser]
    serializer_class = LoanApplicationSerializer

    def get_queryset(self):
        return LoanApplication.objects.all().order_by("-created_at")


class EMIListAPIView(generics.ListAPIView):
    """List unpaid EMIs for the authenticated user."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EMIReadSerializer

    def get_queryset(self):
        return EMI.objects.filter(loan__user=self.request.user, is_paid=False).order_by("due_date")


class EMIPayAPIView(APIView):
    """Pay a single EMI from the authenticated user's wallet."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses={200: EMIPayResponseSerializer, 400: ErrorResponse})
    def post(self, request, emi_id):
        # Only look at this user's EMIs, so other people's EMIs just give a 404
        emi = get_object_or_404(EMI.objects.select_related("loan"), pk=emi_id, loan__user=request.user)

        if emi.is_paid:
            return Response({"detail": "EMI already paid."}, status=status.HTTP_400_BAD_REQUEST)

        with db_transaction.atomic():
            (wallet,) = lock_wallets(request.user.pk)

            # Mark it paid only if it is still unpaid. We check is_paid again
            # inside the update itself, because another request might have paid
            # it after our check above. update() tells us how many rows changed.
            rows_updated = EMI.objects.filter(pk=emi.pk, is_paid=False).update(is_paid=True, paid_amount=F("amount"))
            if rows_updated == 0:
                return Response({"detail": "EMI already paid."}, status=status.HTTP_400_BAD_REQUEST)

            try:
                debit(wallet, emi.amount)
            except InsufficientFunds:
                # Undo the "paid" mark we just made
                db_transaction.set_rollback(True)
                return Response({"detail": "Insufficient funds."}, status=status.HTTP_400_BAD_REQUEST)

            tx = Transaction.objects.create(
                sender=request.user,
                receiver=None,
                transaction_type="withdraw",
                amount=emi.amount,
                status="successful",
                description=f"EMI payment for loan {emi.loan_id} EMI {emi.id}",
            )

        return Response(
            {
                "emi_id": emi.id,
                "loan_id": emi.loan_id,
                "amount": str(emi.amount),
                "transaction_reference": str(tx.reference),
            },
            status=status.HTTP_200_OK,
        )

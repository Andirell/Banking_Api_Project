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
from .serializers import LoanApplicationSerializer, LoanApplyRequestSerializer
from users.models import User
from wallets.models import Wallet
from .utils import create_emis_for_loan
from rest_framework.views import APIView
from .models import EMI
from .serializers import EMIReadSerializer
from django.db import transaction as db_transaction
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
    permission_classes = [permissions.IsAuthenticated]

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
    loan_id = request.data.get("loan_id")
    action = request.data.get("action")  # "approve" or "reject"

    if not loan_id or action not in ("approve", "reject"):
        return Response({"error": "loan_id and action are required"}, status=status.HTTP_400_BAD_REQUEST)

    loan = get_object_or_404(LoanApplication, pk=loan_id)

    if action == "approve":
        loan.status = "approved"
        loan.save()

        # Credit user's wallet (create if missing)
        wallet, _ = Wallet.objects.get_or_create(user=loan.user, defaults={"balance": 0.00})
        wallet.balance += loan.amount
        wallet.save()

        # create EMI schedule
        create_emis_for_loan(loan)
    else:
        loan.status = "rejected"
        loan.save()

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
        emi = get_object_or_404(EMI, pk=emi_id)
        # Ensure emi belongs to the requesting user
        if emi.loan.user.id != request.user.id:
            return Response({"detail": "EMI not found."}, status=status.HTTP_404_NOT_FOUND)

        if emi.is_paid:
            return Response({"detail": "EMI already paid."}, status=status.HTTP_400_BAD_REQUEST)

        # atomic update on wallet and emi to avoid races
        with db_transaction.atomic():
            wallet, _ = Wallet.objects.select_for_update().get_or_create(user=request.user, defaults={"balance": Decimal("0.00")})

            if wallet.balance < emi.amount:
                return Response({"detail": "Insufficient funds."}, status=status.HTTP_400_BAD_REQUEST)

            # debit wallet
            wallet.balance -= emi.amount
            wallet.save()

            # mark emi paid
            emi.paid_amount = emi.amount
            emi.is_paid = True
            emi.save()

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


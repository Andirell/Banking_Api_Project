"""User endpoints and authentication

This module exposes simple authentication and profile endpoints. For
beginners: serializers live in `users/serializers.py`. Many endpoints use
function-based views with `@api_view` for simplicity; feel free to convert
these to class-based views as you learn DRF.
"""

import logging
import os

from django.db import DatabaseError, transaction as db_transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.exceptions import NotFound
from rest_framework import status, permissions
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.views import APIView
from rest_framework.response import Response
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from . import serializers
from .serializers import KYCSubmitSerializer
from .models import OTP, User
from .security import (
    OTPRateLimited,
    check_otp,
    consume_otp,
    issue_otp,
    revoke_user_tokens,
)
from .throttles import OTPRateThrottle
from loans.models import EMI, LoanApplication
from django.conf import settings
from django.core.mail import send_mail
from rest_framework import serializers as drf_serializers
from drf_spectacular.utils import extend_schema
from utils.schemas import (
    MessageResponse,
    ErrorResponse,
    ValidationErrorResponse,
    SignInRequest,
    SignInResponse,
    LogoutRequest,
    ChangePasswordRequest,
    OTPRequest,
    ForgotPasswordRequest,
    VerifyPasswordResetOTPRequest,
    ResetPasswordRequest,
    UpdateUserResponse,
    VerifySigninOTPRequest,
)
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError


# Reusable Swagger Schemas are imported from utils.schemas

# Reused request/response schemas are imported from utils.schemas



logger = logging.getLogger(__name__)






class KYCSubmitAPIView(APIView):
    permission_classes = [IsAuthenticated]
    from rest_framework.parsers import MultiPartParser, FormParser
    parser_classes = [MultiPartParser, FormParser]
    
    @extend_schema(
        summary="Submit KYC documents",
        description="Allow users to submit their KYC documents (identity proof and proof of address).",
        tags=["Users"],
        responses={
            200: MessageResponse,
            400: ErrorResponse,
        },
        request=KYCSubmitSerializer,  # Ensure Swagger UI uses the correct serializer for multipart/form-data
    )
    def post(self, request):
        # Initialize serializer with request data (including file uploads)
        serializer = KYCSubmitSerializer(data=request.data)

        # Validate and raise a ValidationError (DRF will return 400 automatically)
        serializer.is_valid(raise_exception=True)
        from typing import Any, Dict, cast
        validated: Dict[str, Any] = cast(Dict[str, Any], serializer.validated_data)

        user = request.user
        user.identity_document = validated.get('identity_document')
        user.proof_of_address = validated.get('proof_of_address')
        user.kyc_status = 'pending'  # Update KYC status to 'pending'
        user.save()

        return Response({"message": "KYC documents submitted successfully."}, status=status.HTTP_200_OK)

class KYCAdminApprovalAPIView(APIView):
    permission_classes = [IsAdminUser]  # Only admins can access this view
    serializer_class = serializers.UserSerializer  # Add serializer_class for drf-spectacular

    @extend_schema(
        summary="Admin approve/reject KYC",
        description="Allow admins to approve or reject KYC documents submitted by users.",
        tags=["Admin"],
        responses={
            200: MessageResponse,
            400: ErrorResponse,
            404: ErrorResponse,
        },
    )
    def post(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        # Admin can approve or reject KYC
        kyc_status = request.data.get("kyc_status")

        if kyc_status == "verified":
            user.kyc_status = "verified"
            user.kyc_approved = True
        elif kyc_status == "rejected":
            user.kyc_status = "rejected"
            user.kyc_rejection_reason = request.data.get("rejection_reason", "No reason provided")
        else:
            return Response({"error": "Invalid KYC status"}, status=status.HTTP_400_BAD_REQUEST)

        user.save()

        return Response({"message": "KYC status updated successfully."}, status=status.HTTP_200_OK)


class KYCDocumentDownloadAPIView(APIView):
    """Stream a KYC document to its owner or to staff. Nobody else can tell it exists."""
    permission_classes = [IsAuthenticated]
    DOCUMENT_FIELDS = {"identity": "identity_document", "address": "proof_of_address"}

    @extend_schema(
        summary="Download KYC document",
        description="Owner or staff only. `document` is `identity` or `address`.",
        tags=["Users"],
        responses={200: None, 404: ErrorResponse},
    )
    def get(self, request, user_id, document):
        field = self.DOCUMENT_FIELDS.get(document)
        if field is None or (request.user.pk != user_id and not request.user.is_staff):
            raise NotFound("Document not found.")

        owner = get_object_or_404(User, pk=user_id)
        file = getattr(owner, field)
        if not file:
            raise NotFound("Document not found.")
        return FileResponse(file.open("rb"), filename=os.path.basename(file.name))



# Authentication / User Endpoints


@extend_schema(
    summary="Register user",
    description="Create a new user account.",
    tags=["Authentication"],
    request=serializers.UserSerializer,
    responses={
        201: MessageResponse,
        400: ValidationErrorResponse,
    },
)
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def signup(request):
    serializer = serializers.UserSerializer(data=request.data)

    if serializer.is_valid():
        serializer.save()
        return Response(
            {"message": "sign up successful"},
            status=status.HTTP_201_CREATED
        )

    return Response(
        {"errors": serializer.errors},
        status=status.HTTP_400_BAD_REQUEST
    )


@extend_schema(
    summary="Sign in",
    description="Authenticate a user and return JWT access and refresh tokens.",
    tags=["Authentication"],
    request=SignInRequest,
    responses={
        200: SignInResponse,
        400: ErrorResponse,
        401: ErrorResponse,
    },
)
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def signin(request):
    email = request.data.get("email")
    password = request.data.get("password")

    if not email or not password:
        return Response(
            {"error": "email and password are required"},
            status=status.HTTP_400_BAD_REQUEST
        )

    user = authenticate(request, email=email, password=password)

    if user is None:
        return Response(
            {"error": "invalid credentials"},
            status=status.HTTP_401_UNAUTHORIZED
        )

    # Instead of immediately issuing tokens, generate an OTP and require
    # the user to verify it. This implements a two-step signin flow.
    # The challenge is stored against this user, so it can only ever log in
    # this account. If it can't be stored, fail closed: no weaker fallback.
    try:
        otp_code = issue_otp(user, "signin")
    except OTPRateLimited:
        return Response(
            {"error": "too many sign-in codes requested, try again later"},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )
    except DatabaseError:
        logger.exception("Could not store sign-in OTP")
        return Response(
            {"error": "sign-in is temporarily unavailable"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    # If the code can't be delivered the user can't finish signing in, so say
    # so instead of reporting success, and retire the undeliverable challenge.
    try:
        send_mail(
            subject="Your sign-in OTP",
            message=f"Use this OTP to complete sign in: {otp_code}",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
    except Exception:
        logger.exception("Could not email sign-in OTP to user %s", user.pk)
        OTP.objects.filter(user=user, purpose="signin", is_used=False).update(is_used=True)
        return Response(
            {"error": "could not send the sign-in code, try again later"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    return Response(
        {
            "message": "OTP sent. Verify OTP to complete signin.",
            "next": "verify_signin_otp",
            "email": user.email,
        },
        status=status.HTTP_200_OK,
    )


@extend_schema(
    summary="Verify signin OTP",
    description="Verify the OTP for a signin attempt and return JWT tokens.",
    tags=["Authentication"],
    request=VerifySigninOTPRequest,
    responses={200: SignInResponse, 400: ErrorResponse, 401: ErrorResponse},
)
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([OTPRateThrottle])
def verify_signin_otp(request):
    email = request.data.get("email")
    otp = request.data.get("otp")

    if not email or not otp:
        return Response({"error": "email and otp are required"}, status=status.HTTP_400_BAD_REQUEST)

    user = User.objects.filter(email=email, is_active=True).first()
    if user is None:
        return Response({"error": "invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)

    try:
        otp_obj = check_otp(user, "signin", otp)
        # Tokens are issued only by the request that wins the conditional update.
        if otp_obj is None or not consume_otp(otp_obj.pk):
            return Response({"error": "invalid or expired otp"}, status=status.HTTP_400_BAD_REQUEST)
    except DatabaseError:
        logger.exception("Could not verify sign-in OTP")
        return Response(
            {"error": "sign-in is temporarily unavailable"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    # Issue tokens
    access = AccessToken.for_user(user)
    refresh = RefreshToken.for_user(user)

    return Response({
        "message": "sign in successful",
        "access_token": str(access),
        "refresh_token": str(refresh),
    }, status=status.HTTP_200_OK)


@extend_schema(
    summary="Get current user",
    description="Retrieve the authenticated user's profile.",
    tags=["Users"],
    responses={
        200: serializers.UserProfileSerializer,
    },
)
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def get_me(request):
    serializer = serializers.UserProfileSerializer(request.user)
    return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    summary="Update current user",
    description="Update the authenticated user's profile. PUT replaces all allowed fields, PATCH updates partially.",
    tags=["Users"],
    request=serializers.UpdateUserSerializer,
    responses={
        200: UpdateUserResponse,
        400: ValidationErrorResponse,
    },
)
@api_view(["PUT", "PATCH"])
@permission_classes([permissions.IsAuthenticated])
def update_user(request):
    partial = request.method == "PATCH"

    serializer = serializers.UpdateUserSerializer(
        request.user,
        data=request.data,
        partial=partial
    )

    if serializer.is_valid():
        serializer.save()
        return Response(
            {
                "message": "user updated successfully",
                "user": serializers.UserProfileSerializer(request.user).data
            },
            status=status.HTTP_200_OK
        )

    return Response(
        {"errors": serializer.errors},
        status=status.HTTP_400_BAD_REQUEST
    )

@extend_schema(
    summary="Change password",
    description="Change the authenticated user's password.",
    tags=["Authentication"],
    request=ChangePasswordRequest,
    responses={
        200: MessageResponse,
        400: ErrorResponse,
    },
)

@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def change_password(request):
    old_password = request.data.get("old_password")
    new_password = request.data.get("new_password")
    confirm_password = request.data.get("confirm_password")

    if not old_password or not new_password or not confirm_password:
        return Response(
            {"error": "all password fields are required"},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not request.user.check_password(old_password):
        return Response(
            {"error": "old password is incorrect"},
            status=status.HTTP_400_BAD_REQUEST
        )

    if new_password != confirm_password:
        return Response(
            {"error": "new passwords do not match"},
            status=status.HTTP_400_BAD_REQUEST
        )

    if old_password == new_password:
        return Response(
            {"error": "new password must be different from old password"},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        validate_password(new_password, request.user)
    except DjangoValidationError as e:
        return Response(
            {"error": e.messages[0]},
            status=status.HTTP_400_BAD_REQUEST
        )

    request.user.set_password(new_password)
    request.user.save()
    # Existing access tokens die with the old password hash (CHECK_REVOKE_TOKEN);
    # refresh tokens are blacklisted here.
    revoke_user_tokens(request.user)

    return Response(
        {"message": "password changed successfully, please sign in again"},
        status=status.HTTP_200_OK
    )

@extend_schema(
    summary="Logout user",
    description="Blacklist the refresh token and log the user out.",
    tags=["Authentication"],
    request=LogoutRequest,
    responses={
        200: MessageResponse,
        400: ErrorResponse,
    },
)
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def logout_view(request):
    refresh_token = request.data.get("refresh_token")

    if not refresh_token:
        return Response(
            {"error": "refresh_token is required"},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        token = RefreshToken(refresh_token)
        token.blacklist()
    except TokenError:
        return Response(
            {"error": "invalid or expired refresh token"},
            status=status.HTTP_400_BAD_REQUEST
        )
    except Exception:
        return Response(
            {"error": "token blacklisting is not enabled"},
            status=status.HTTP_400_BAD_REQUEST
        )

    return Response(
        {"message": "logout successful"},
        status=status.HTTP_200_OK
    )


@extend_schema(
    summary="Delete current user",
    description="Delete the authenticated user's account.",
    tags=["Users"],
    responses={
        200: MessageResponse,
    },
)
@api_view(["DELETE"])
@permission_classes([permissions.IsAuthenticated])
def delete_user(request):
    # Accounts are closed, never hard-deleted: loans, EMIs and transactions
    # (including other users' transfers) must survive the account.
    user = request.user

    if EMI.objects.filter(loan__user=user, is_paid=False).exists():
        return Response(
            {"error": "account has unpaid loan installments"},
            status=status.HTTP_409_CONFLICT
        )
    if LoanApplication.objects.filter(user=user, status="pending").exists():
        return Response(
            {"error": "account has a pending loan application"},
            status=status.HTTP_409_CONFLICT
        )
    wallet = getattr(user, "wallet", None)
    if wallet is not None and wallet.balance != 0:
        return Response(
            {"error": "withdraw your remaining balance before closing the account"},
            status=status.HTTP_409_CONFLICT
        )

    with db_transaction.atomic():
        for document in (user.identity_document, user.proof_of_address):
            if document:
                document.delete(save=False)
        user.email = f"deleted-{user.pk}@deleted.invalid"
        user.first_name = "Deleted"
        user.last_name = "User"
        user.phone_number = None
        user.bvn = None
        user.address = None
        user.date_of_birth = None
        user.nationality = None
        user.is_active = False
        user.set_unusable_password()
        user.save()
        revoke_user_tokens(user)

    return Response(
        {"message": "account closed successfully"},
        status=status.HTTP_200_OK
    )


@extend_schema(
    summary="Block user",
    description="Deactivate a user account. Admin only.",
    tags=["Admin"],
    request=None,
    responses={
        200: MessageResponse,
        403: ErrorResponse,
        404: ErrorResponse,
    },
)
@api_view(["PATCH"])
@permission_classes([permissions.IsAuthenticated])
def block_user(request, id):
    if request.user.role != "admin":
        return Response(
            {"error": "only admin can block users"},
            status=status.HTTP_403_FORBIDDEN
        )

    try:
        user = User.objects.get(id=id)
    except User.DoesNotExist:
        return Response(
            {"error": "user not found"},
            status=status.HTTP_404_NOT_FOUND
        )

    if user == request.user:
        return Response(
            {"error": "admin cannot block self"},
            status=status.HTTP_400_BAD_REQUEST
        )

    user.is_active = False
    user.save()

    return Response(
        {"message": "user blocked successfully"},
        status=status.HTTP_200_OK
    )


@extend_schema(
    summary="Unblock user",
    description="Reactivate a user account. Admin only.",
    tags=["Admin"],
    request=None,
    responses={
        200: MessageResponse,
        403: ErrorResponse,
        404: ErrorResponse,
    },
)
@api_view(["PATCH"])
@permission_classes([permissions.IsAuthenticated])
def unblock_user(request, id):
    if request.user.role != "admin":
        return Response(
            {"error": "only admin can unblock users"},
            status=status.HTTP_403_FORBIDDEN
        )

    try:
        user = User.objects.get(id=id)
    except User.DoesNotExist:
        return Response(
            {"error": "user not found"},
            status=status.HTTP_404_NOT_FOUND
        )

    user.is_active = True
    user.save()

    return Response(
        {"message": "user unblocked successfully"},
        status=status.HTTP_200_OK
    )


# ============================================================================
# OTP Endpoints
# ============================================================================

@extend_schema(
    summary="Send OTP",
    description="Send a one-time password to the authenticated user's email.",
    tags=["OTP"],
    request=None,
    responses={
        200: MessageResponse,
    },
)
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def send_otp_view(request):
    # Stored in the database against this user, like the sign-in and reset
    # codes, so the attempt and issuance caps apply here too.
    try:
        otp = issue_otp(request.user, "verify")
    except OTPRateLimited:
        return Response(
            {"error": "too many codes requested, try again later"},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    try:
        send_mail(
            subject="Your OTP Code",
            message=f"Your OTP is {otp}. It will expire in 5 minutes.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[request.user.email],
            fail_silently=False,
        )
    except Exception:
        logger.exception("Could not email OTP to user %s", request.user.pk)
        OTP.objects.filter(user=request.user, purpose="verify", is_used=False).update(is_used=True)
        return Response(
            {"error": "could not send the code, try again later"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    return Response(
        {"message": "otp sent successfully"},
        status=status.HTTP_200_OK
    )


@extend_schema(
    summary="Verify OTP",
    description="Verify the OTP previously sent to the authenticated user.",
    tags=["OTP"],
    request=OTPRequest,
    responses={
        200: MessageResponse,
        400: ErrorResponse,
    },
)
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def verify_otp_view(request):
    otp_obj = check_otp(request.user, "verify", request.data.get("otp"))
    if otp_obj is None or not consume_otp(otp_obj.pk, user=request.user, purpose="verify"):
        return Response(
            {"error": "invalid or expired otp, request a new one"},
            status=status.HTTP_400_BAD_REQUEST
        )

    return Response(
        {"message": "otp verified successfully"},
        status=status.HTTP_200_OK
    )

@extend_schema(
    summary="Request password reset",
    description="Send a password reset OTP to the user's email.",
    tags=["Authentication"],
    request=ForgotPasswordRequest,
    responses={
        200: MessageResponse,
        400: ErrorResponse,
    },
)
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([OTPRateThrottle])
def request_password_reset(request):
    email = request.data.get("email")

    if not email:
        return Response(
            {"error": "email is required"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Same answer whether or not the account exists or is over its budget,
    # so this endpoint can't be used to discover accounts.
    generic = Response(
        {"message": "if an account with this email exists, an otp has been sent"},
        status=status.HTTP_200_OK
    )

    user = User.objects.filter(email=email, is_active=True).first()
    if user is None:
        return generic

    try:
        otp = issue_otp(user, "password_reset")
    except OTPRateLimited:
        return generic

    request.session.pop("password_reset_otp_id", None)

    try:
        send_mail(
            subject="Password Reset OTP",
            message=f"Your password reset OTP is {otp}. It will expire in 5 minutes.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
    except Exception:
        # Keep the generic answer (no account enumeration); the failure is logged.
        logger.exception("Could not email password reset OTP to user %s", user.pk)
        OTP.objects.filter(user=user, purpose="password_reset", is_used=False).update(is_used=True)

    return generic

@extend_schema(
    summary="Verify password reset OTP",
    description="Verify the OTP sent for password reset.",
    tags=["Authentication"],
    request=VerifyPasswordResetOTPRequest,
    responses={
        200: MessageResponse,
        400: ErrorResponse,
    },
)
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([OTPRateThrottle])
def verify_password_reset_otp(request):
    email = request.data.get("email")
    otp = request.data.get("otp")

    if not email or not otp:
        return Response(
            {"error": "email and otp are required"},
            status=status.HTTP_400_BAD_REQUEST
        )

    user = User.objects.filter(email=email, is_active=True).first()
    otp_obj = check_otp(user, "password_reset", otp) if user else None

    # Record the verification on the challenge itself; it still expires at
    # its original deadline and is consumed by reset_password.
    verified = otp_obj is not None and OTP.objects.filter(
        pk=otp_obj.pk, is_used=False, expires_at__gt=timezone.now()
    ).update(verified_at=timezone.now()) == 1
    if not verified:
        return Response(
            {"error": "invalid or expired otp"},
            status=status.HTTP_400_BAD_REQUEST
        )

    request.session["password_reset_otp_id"] = otp_obj.pk

    return Response(
        {"message": "password reset otp verified successfully"},
        status=status.HTTP_200_OK
    )

@extend_schema(
    summary="Reset password",
    description="Reset the user's password after OTP verification.",
    tags=["Authentication"],
    request=ResetPasswordRequest,
    responses={
        200: MessageResponse,
        400: ErrorResponse,
    },
)
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([OTPRateThrottle])
def reset_password(request):
    email = request.data.get("email")
    new_password = request.data.get("new_password")
    confirm_password = request.data.get("confirm_password")

    if not email or not new_password or not confirm_password:
        return Response(
            {"error": "email, new_password and confirm_password are required"},
            status=status.HTTP_400_BAD_REQUEST
        )

    otp_id = request.session.get("password_reset_otp_id")
    otp_obj = (
        OTP.objects.select_related("user").filter(pk=otp_id, purpose="password_reset").first()
        if otp_id else None
    )
    if otp_obj is None or otp_obj.user.email != email:
        return Response(
            {"error": "invalid password reset session"},
            status=status.HTTP_400_BAD_REQUEST
        )

    if new_password != confirm_password:
        return Response(
            {"error": "passwords do not match"},
            status=status.HTTP_400_BAD_REQUEST
        )

    user = otp_obj.user
    try:
        validate_password(new_password, user)
    except DjangoValidationError as e:
        return Response(
            {"error": e.messages[0]},
            status=status.HTTP_400_BAD_REQUEST
        )

    with db_transaction.atomic():
        # Single use, verified, and still inside the challenge's deadline.
        if not consume_otp(otp_obj.pk, purpose="password_reset", verified_at__isnull=False):
            request.session.pop("password_reset_otp_id", None)
            return Response(
                {"error": "password reset has expired, request a new code"},
                status=status.HTTP_400_BAD_REQUEST
            )
        user.set_password(new_password)
        user.save()
        revoke_user_tokens(user)

    request.session.pop("password_reset_otp_id", None)

    return Response(
        {"message": "password reset successful"},
        status=status.HTTP_200_OK
    )

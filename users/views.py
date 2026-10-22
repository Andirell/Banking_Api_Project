"""User endpoints: sign up, sign in (with an emailed code), profile, KYC,
password change/reset, closing an account, and blocking users (admin).
"""

import logging
import os

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db import DatabaseError, IntegrityError, transaction as db_transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from loans.models import EMI, LoanApplication
from utils.schemas import (
    ChangePasswordRequest,
    ErrorResponse,
    ForgotPasswordRequest,
    LogoutRequest,
    MessageResponse,
    OTPRequest,
    ResetPasswordRequest,
    SignInRequest,
    SignInResponse,
    UpdateUserResponse,
    ValidationErrorResponse,
    VerifyPasswordResetOTPRequest,
    VerifySigninOTPRequest,
)
from wallets.services import lock_wallets

from . import serializers
from .models import OTP, User
from .security import OTPRateLimited, check_otp, consume_otp, issue_otp, revoke_user_tokens
from .throttles import OTPRateThrottle, SignupRateThrottle

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def error(message, status_code=status.HTTP_400_BAD_REQUEST):
    return Response({"error": message}, status=status_code)


def message(text, status_code=status.HTTP_200_OK):
    return Response({"message": text}, status=status_code)


def email_code(user, purpose, subject, body):
    # Email a one-time code. Returns True if it was sent.
    # If sending fails, the code is cancelled because the user can never
    # receive it, and the error is logged.
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
        return True
    except Exception:
        logger.exception("Could not email %s code to user %s", purpose, user.pk)
        OTP.objects.filter(user=user, purpose=purpose, is_used=False).update(is_used=True)
        return False


def check_new_password(password, user=None):
    # Returns an error message, or None if the password is fine
    try:
        validate_password(password, user)
    except DjangoValidationError as e:
        return e.messages[0]
    return None


# ---------------------------------------------------------------------------
# KYC
# ---------------------------------------------------------------------------

class KYCSubmitAPIView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        summary="Submit KYC documents",
        description="Allow users to submit their KYC documents (identity proof and proof of address).",
        tags=["Users"],
        responses={200: MessageResponse, 400: ErrorResponse},
        request=serializers.KYCSubmitSerializer,
    )
    def post(self, request):
        serializer = serializers.KYCSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user

        # Remember the old files so we can delete them after saving the new ones
        old_files = []
        if user.identity_document:
            old_files.append(user.identity_document)
        if user.proof_of_address:
            old_files.append(user.proof_of_address)

        user.identity_document = serializer.validated_data.get("identity_document")
        user.proof_of_address = serializer.validated_data.get("proof_of_address")
        # New documents need to be checked again, even if the old ones were approved
        user.kyc_status = "pending"
        user.kyc_approved = False
        user.kyc_rejection_reason = None
        user.save()

        # We don't keep old ID documents
        for old_file in old_files:
            old_file.storage.delete(old_file.name)

        return message("KYC documents submitted successfully.")


class KYCAdminApprovalAPIView(APIView):
    permission_classes = [IsAdminUser]
    serializer_class = serializers.UserSerializer  # only for the Swagger docs

    @extend_schema(
        summary="Admin approve/reject KYC",
        description="Allow admins to approve or reject KYC documents submitted by users.",
        tags=["Admin"],
        responses={200: MessageResponse, 400: ErrorResponse, 404: ErrorResponse},
    )
    def post(self, request, user_id):
        user = User.objects.filter(id=user_id).first()
        if user is None:
            return error("User not found", status.HTTP_404_NOT_FOUND)

        new_status = request.data.get("kyc_status")

        if new_status == "verified":
            if not user.identity_document or not user.proof_of_address:
                return error("User has not submitted both KYC documents")
            user.kyc_status = "verified"
            user.kyc_approved = True
        elif new_status == "rejected":
            user.kyc_status = "rejected"
            user.kyc_approved = False
            user.kyc_rejection_reason = request.data.get("rejection_reason", "No reason provided")
        else:
            return error("Invalid KYC status")

        user.save()
        return message("KYC status updated successfully.")


class KYCDocumentDownloadAPIView(APIView):
    # Only the owner of the document or staff can download it.
    # Everyone else gets "not found", so they can't even tell it exists.
    permission_classes = [IsAuthenticated]
    DOCUMENT_FIELDS = {"identity": "identity_document", "address": "proof_of_address"}

    @extend_schema(
        summary="Download KYC document",
        description="Owner or staff only. `document` is `identity` or `address`.",
        tags=["Users"],
        responses={200: None, 404: ErrorResponse},
    )
    def get(self, request, user_id, document):
        field_name = self.DOCUMENT_FIELDS.get(document)
        if field_name is None:
            raise NotFound("Document not found.")

        is_owner = request.user.pk == user_id
        if not is_owner and not request.user.is_staff:
            raise NotFound("Document not found.")

        owner = get_object_or_404(User, pk=user_id)
        file = getattr(owner, field_name)
        if not file:
            raise NotFound("Document not found.")
        return FileResponse(file.open("rb"), filename=os.path.basename(file.name))


# ---------------------------------------------------------------------------
# Sign up and sign in
# ---------------------------------------------------------------------------

@extend_schema(
    summary="Register user",
    description="Create a new user account.",
    tags=["Authentication"],
    request=serializers.UserSerializer,
    responses={201: MessageResponse, 400: ValidationErrorResponse},
)
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([SignupRateThrottle])
def signup(request):
    serializer = serializers.UserSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    try:
        with db_transaction.atomic():
            serializer.save()
    except IntegrityError:
        # Someone else signed up with the same email/BVN/phone at the same moment
        return Response(
            {"errors": {"non_field_errors": [serializers.DUPLICATE_DETAILS_ERROR]}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    return message("sign up successful", status.HTTP_201_CREATED)


@extend_schema(
    summary="Sign in",
    description="Authenticate a user and return JWT access and refresh tokens.",
    tags=["Authentication"],
    request=SignInRequest,
    responses={200: SignInResponse, 400: ErrorResponse, 401: ErrorResponse},
)
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([OTPRateThrottle])
def signin(request):
    # Step 1 of signing in: check the password and email a code.
    # Step 2 is verify_signin_otp below, which gives the tokens.
    email = request.data.get("email")
    password = request.data.get("password")
    if not email or not password:
        return error("email and password are required")

    # This goes through users/backends.py, which also handles the lockout
    user = authenticate(request, email=email, password=password)
    if user is None:
        return error("invalid credentials", status.HTTP_401_UNAUTHORIZED)

    try:
        code = issue_otp(user, "signin")
    except OTPRateLimited:
        return error("too many sign-in codes requested, try again later", status.HTTP_429_TOO_MANY_REQUESTS)
    except DatabaseError:
        # If we can't save the code we stop here. We never fall back to
        # a weaker way of signing in.
        logger.exception("Could not store sign-in OTP")
        return error("sign-in is temporarily unavailable", status.HTTP_503_SERVICE_UNAVAILABLE)

    sent = email_code(user, "signin", "Your sign-in OTP", f"Use this OTP to complete sign in: {code}")
    if not sent:
        return error("could not send the sign-in code, try again later", status.HTTP_503_SERVICE_UNAVAILABLE)

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
    code = request.data.get("otp")
    if not email or not code:
        return error("email and otp are required")

    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if user is None:
        return error("invalid credentials", status.HTTP_401_UNAUTHORIZED)

    try:
        otp = check_otp(user, "signin", code)
        # consume_otp only returns True for one request, so the same code
        # can't log in twice even if two requests arrive together
        if otp is None or not consume_otp(otp.pk):
            return error("invalid or expired otp")
    except DatabaseError:
        logger.exception("Could not verify sign-in OTP")
        return error("sign-in is temporarily unavailable", status.HTTP_503_SERVICE_UNAVAILABLE)

    access = AccessToken.for_user(user)
    refresh = RefreshToken.for_user(user)
    return Response(
        {
            "message": "sign in successful",
            "access_token": str(access),
            "refresh_token": str(refresh),
        },
        status=status.HTTP_200_OK,
    )


@extend_schema(
    summary="Logout user",
    description="Blacklist the refresh token and log the user out.",
    tags=["Authentication"],
    request=LogoutRequest,
    responses={200: MessageResponse, 400: ErrorResponse},
)
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def logout_view(request):
    refresh_token = request.data.get("refresh_token")
    if not refresh_token:
        return error("refresh_token is required")

    try:
        token = RefreshToken(refresh_token)
    except TokenError:
        return error("invalid or expired refresh token")

    # You can only log out your own session, not someone else's
    if str(token.get("user_id")) != str(request.user.pk):
        return error("invalid or expired refresh token")

    token.blacklist()
    return message("logout successful")


# ---------------------------------------------------------------------------
# My account
# ---------------------------------------------------------------------------

@extend_schema(
    summary="Get current user",
    description="Retrieve the authenticated user's profile.",
    tags=["Users"],
    responses={200: serializers.UserProfileSerializer},
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
    responses={200: UpdateUserResponse, 400: ValidationErrorResponse},
)
@api_view(["PUT", "PATCH"])
@permission_classes([permissions.IsAuthenticated])
def update_user(request):
    is_partial = request.method == "PATCH"
    serializer = serializers.UpdateUserSerializer(request.user, data=request.data, partial=is_partial)

    if not serializer.is_valid():
        return Response({"errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    serializer.save()
    return Response(
        {
            "message": "user updated successfully",
            "user": serializers.UserProfileSerializer(request.user).data,
        },
        status=status.HTTP_200_OK,
    )


@extend_schema(
    summary="Change password",
    description="Change the authenticated user's password.",
    tags=["Authentication"],
    request=ChangePasswordRequest,
    responses={200: MessageResponse, 400: ErrorResponse},
)
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def change_password(request):
    old_password = request.data.get("old_password")
    new_password = request.data.get("new_password")
    confirm_password = request.data.get("confirm_password")

    if not old_password or not new_password or not confirm_password:
        return error("all password fields are required")
    if not request.user.check_password(old_password):
        return error("old password is incorrect")
    if new_password != confirm_password:
        return error("new passwords do not match")
    if old_password == new_password:
        return error("new password must be different from old password")

    problem = check_new_password(new_password, request.user)
    if problem:
        return error(problem)

    request.user.set_password(new_password)
    request.user.save()
    # Log out everywhere. Must be called every time a password changes.
    revoke_user_tokens(request.user)

    return message("password changed successfully, please sign in again")


@extend_schema(
    summary="Delete current user",
    description="Delete the authenticated user's account.",
    tags=["Users"],
    responses={200: MessageResponse},
)
@api_view(["DELETE"])
@permission_classes([permissions.IsAuthenticated])
def delete_user(request):
    # We never really delete a user, because their loans and transactions
    # (including transfers to other people) must stay in the records.
    # Instead we remove their personal details and close the account.
    user = request.user

    with db_transaction.atomic():
        # Lock the wallet first. Every deposit/transfer/loan payout takes this
        # same lock, so no money can arrive while we are closing the account.
        (wallet,) = lock_wallets(user.pk)

        if EMI.objects.filter(loan__user=user, is_paid=False).exists():
            return error("account has unpaid loan installments", status.HTTP_409_CONFLICT)
        if LoanApplication.objects.filter(user=user, status="pending").exists():
            return error("account has a pending loan application", status.HTTP_409_CONFLICT)
        if wallet.balance != 0:
            return error("withdraw your remaining balance before closing the account", status.HTTP_409_CONFLICT)

        # Delete their ID documents
        if user.identity_document:
            user.identity_document.delete(save=False)
        if user.proof_of_address:
            user.proof_of_address.delete(save=False)

        # Remove personal details
        user.email = f"deleted-{user.pk}@deleted.invalid"
        user.first_name = "Deleted"
        user.last_name = "User"
        user.phone_number = None
        user.bvn = None
        user.address = None
        user.date_of_birth = None
        user.nationality = None

        # Close the account so nobody can log in to it again
        user.is_active = False
        user.closed_at = timezone.now()
        user.set_unusable_password()
        user.save()
        revoke_user_tokens(user)

    return message("account closed successfully")


# ---------------------------------------------------------------------------
# Admin: block and unblock users
# ---------------------------------------------------------------------------

@extend_schema(
    summary="Block user",
    description="Deactivate a user account. Admin only.",
    tags=["Admin"],
    request=None,
    responses={200: MessageResponse, 403: ErrorResponse, 404: ErrorResponse},
)
@api_view(["PATCH"])
@permission_classes([permissions.IsAuthenticated])
def block_user(request, id):
    if request.user.role != "admin":
        return error("only admin can block users", status.HTTP_403_FORBIDDEN)

    user = User.objects.filter(id=id).first()
    if user is None:
        return error("user not found", status.HTTP_404_NOT_FOUND)
    if user == request.user:
        return error("admin cannot block self")

    user.is_active = False
    user.save()
    return message("user blocked successfully")


@extend_schema(
    summary="Unblock user",
    description="Reactivate a user account. Admin only.",
    tags=["Admin"],
    request=None,
    responses={200: MessageResponse, 403: ErrorResponse, 404: ErrorResponse},
)
@api_view(["PATCH"])
@permission_classes([permissions.IsAuthenticated])
def unblock_user(request, id):
    if request.user.role != "admin":
        return error("only admin can unblock users", status.HTTP_403_FORBIDDEN)

    user = User.objects.filter(id=id).first()
    if user is None:
        return error("user not found", status.HTTP_404_NOT_FOUND)
    if user.closed_at is not None:
        return error("closed accounts cannot be reactivated")

    user.is_active = True
    user.save()
    return message("user unblocked successfully")


# ---------------------------------------------------------------------------
# OTP for logged-in users
# ---------------------------------------------------------------------------

@extend_schema(
    summary="Send OTP",
    description="Send a one-time password to the authenticated user's email.",
    tags=["OTP"],
    request=None,
    responses={200: MessageResponse},
)
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def send_otp_view(request):
    try:
        code = issue_otp(request.user, "verify")
    except OTPRateLimited:
        return error("too many codes requested, try again later", status.HTTP_429_TOO_MANY_REQUESTS)

    sent = email_code(request.user, "verify", "Your OTP Code", f"Your OTP is {code}. It will expire in 5 minutes.")
    if not sent:
        return error("could not send the code, try again later", status.HTTP_503_SERVICE_UNAVAILABLE)

    return message("otp sent successfully")


@extend_schema(
    summary="Verify OTP",
    description="Verify the OTP previously sent to the authenticated user.",
    tags=["OTP"],
    request=OTPRequest,
    responses={200: MessageResponse, 400: ErrorResponse},
)
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def verify_otp_view(request):
    otp = check_otp(request.user, "verify", request.data.get("otp"))
    if otp is None or not consume_otp(otp.pk, user=request.user, purpose="verify"):
        return error("invalid or expired otp, request a new one")

    return message("otp verified successfully")


# ---------------------------------------------------------------------------
# Forgot password (3 steps: request a code, verify it, set a new password)
# ---------------------------------------------------------------------------

@extend_schema(
    summary="Request password reset",
    description="Send a password reset OTP to the user's email.",
    tags=["Authentication"],
    request=ForgotPasswordRequest,
    responses={200: MessageResponse, 400: ErrorResponse},
)
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([OTPRateThrottle])
def request_password_reset(request):
    email = request.data.get("email")
    if not email:
        return error("email is required")

    # We always give this same answer, whether the account exists or not.
    # Otherwise people could use this page to find out who has an account.
    same_answer = message("if an account with this email exists, an otp has been sent")

    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if user is None:
        return same_answer

    try:
        code = issue_otp(user, "password_reset")
    except OTPRateLimited:
        return same_answer

    # Starting a new reset cancels any earlier verified code in this session
    request.session.pop("password_reset_otp_id", None)

    # If the email fails we still give the same answer (the error is logged)
    email_code(
        user,
        "password_reset",
        "Password Reset OTP",
        f"Your password reset OTP is {code}. It will expire in 5 minutes.",
    )
    return same_answer


@extend_schema(
    summary="Verify password reset OTP",
    description="Verify the OTP sent for password reset.",
    tags=["Authentication"],
    request=VerifyPasswordResetOTPRequest,
    responses={200: MessageResponse, 400: ErrorResponse},
)
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([OTPRateThrottle])
def verify_password_reset_otp(request):
    email = request.data.get("email")
    code = request.data.get("otp")
    if not email or not code:
        return error("email and otp are required")

    user = User.objects.filter(email__iexact=email, is_active=True).first()
    otp = None
    if user is not None:
        otp = check_otp(user, "password_reset", code)

    if otp is None:
        return error("invalid or expired otp")

    # Mark the code as verified (but not used yet). It still expires at its
    # normal time, and reset_password uses it up in the next step.
    rows_updated = OTP.objects.filter(
        pk=otp.pk, is_used=False, expires_at__gt=timezone.now()
    ).update(verified_at=timezone.now())
    if rows_updated != 1:
        return error("invalid or expired otp")

    # Only the id of the verified code goes in the session
    request.session["password_reset_otp_id"] = otp.pk
    return message("password reset otp verified successfully")


@extend_schema(
    summary="Reset password",
    description="Reset the user's password after OTP verification.",
    tags=["Authentication"],
    request=ResetPasswordRequest,
    responses={200: MessageResponse, 400: ErrorResponse},
)
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([OTPRateThrottle])
def reset_password(request):
    email = request.data.get("email")
    new_password = request.data.get("new_password")
    confirm_password = request.data.get("confirm_password")
    if not email or not new_password or not confirm_password:
        return error("email, new_password and confirm_password are required")

    # Find the code that was verified in the previous step
    otp = None
    otp_id = request.session.get("password_reset_otp_id")
    if otp_id:
        otp = OTP.objects.select_related("user").filter(pk=otp_id, purpose="password_reset").first()

    # The email must belong to the same user the code was sent to
    if otp is None or otp.user.email != str(email).strip().lower():
        return error("invalid password reset session")

    if new_password != confirm_password:
        return error("passwords do not match")

    user = otp.user
    problem = check_new_password(new_password, user)
    if problem:
        return error(problem)

    with db_transaction.atomic():
        # Use up the code. This only works once, only if it was verified,
        # and only if it hasn't expired yet.
        if not consume_otp(otp.pk, purpose="password_reset", verified_at__isnull=False):
            request.session.pop("password_reset_otp_id", None)
            return error("password reset has expired, request a new code")

        user.set_password(new_password)
        # Proving you own the email is allowed to unlock a locked account
        user.failed_signin_attempts = 0
        user.signin_locked_until = None
        user.save()
        revoke_user_tokens(user)

    request.session.pop("password_reset_otp_id", None)
    return message("password reset successful")

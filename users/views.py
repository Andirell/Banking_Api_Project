"""User endpoints and authentication

This module exposes simple authentication and profile endpoints. For
beginners: serializers live in `users/serializers.py`. Many endpoints use
function-based views with `@api_view` for simplicity; feel free to convert
these to class-based views as you learn DRF.
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework import status, permissions
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.views import APIView
from rest_framework.response import Response
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from . import serializers
from .serializers import KYCSubmitSerializer
from .models import User
import random
import time
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
)
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError


# Reusable Swagger Schemas are imported from utils.schemas

# Reused request/response schemas are imported from utils.schemas



# Helpers

def generate_otp():
    return str(random.randint(100000, 999999))






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

    access = AccessToken.for_user(user)
    refresh = RefreshToken.for_user(user)

    return Response(
        {
            "message": "sign in successful",
            "access_token": str(access),
            "refresh_token": str(refresh),
        },
        status=status.HTTP_200_OK
    )


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

    return Response(
        {"message": "password changed successfully"},
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
    request.user.delete()
    return Response(
        {"message": "account deleted successfully"},
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
    otp = generate_otp()

    request.session["otp_code"] = otp
    request.session["otp_expiry"] = time.time() + 300

    send_mail(
        subject="Your OTP Code",
        message=f"Your OTP is {otp}. It will expire in 5 minutes.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[request.user.email],
        fail_silently=False,
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
    otp = request.data.get("otp")

    saved_otp = request.session.get("otp_code")
    saved_expiry = request.session.get("otp_expiry")

    if not saved_otp or not saved_expiry:
        return Response(
            {"error": "no otp found, request a new one"},
            status=status.HTTP_400_BAD_REQUEST
        )

    if time.time() > saved_expiry:
        request.session.pop("otp_code", None)
        request.session.pop("otp_expiry", None)
        return Response(
            {"error": "otp has expired"},
            status=status.HTTP_400_BAD_REQUEST
        )

    if otp != saved_otp:
        return Response(
            {"error": "invalid otp"},
            status=status.HTTP_400_BAD_REQUEST
        )

    request.session.pop("otp_code", None)
    request.session.pop("otp_expiry", None)

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
def request_password_reset(request):
    email = request.data.get("email")

    if not email:
        return Response(
            {"error": "email is required"},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        # Security best practice: don't reveal whether the email exists
        return Response(
            {"message": "if an account with this email exists, an otp has been sent"},
            status=status.HTTP_200_OK
        )

    otp = generate_otp()

    request.session["password_reset_email"] = user.email
    request.session["password_reset_otp"] = otp
    request.session["password_reset_expiry"] = time.time() + 300
    request.session["password_reset_verified"] = False

    send_mail(
        subject="Password Reset OTP",
        message=f"Your password reset OTP is {otp}. It will expire in 5 minutes.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )

    return Response(
        {"message": "if an account with this email exists, an otp has been sent"},
        status=status.HTTP_200_OK
    )

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
def verify_password_reset_otp(request):
    email = request.data.get("email")
    otp = request.data.get("otp")

    saved_email = request.session.get("password_reset_email")
    saved_otp = request.session.get("password_reset_otp")
    saved_expiry = request.session.get("password_reset_expiry")

    if not saved_email or not saved_otp or not saved_expiry:
        return Response(
            {"error": "no password reset otp found, request a new one"},
            status=status.HTTP_400_BAD_REQUEST
        )

    if email != saved_email:
        return Response(
            {"error": "invalid email for this otp"},
            status=status.HTTP_400_BAD_REQUEST
        )

    if time.time() > saved_expiry:
        request.session.pop("password_reset_email", None)
        request.session.pop("password_reset_otp", None)
        request.session.pop("password_reset_expiry", None)
        request.session.pop("password_reset_verified", None)

        return Response(
            {"error": "otp has expired"},
            status=status.HTTP_400_BAD_REQUEST
        )

    if otp != saved_otp:
        return Response(
            {"error": "invalid otp"},
            status=status.HTTP_400_BAD_REQUEST
        )

    request.session["password_reset_verified"] = True

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
        404: ErrorResponse,
    },
)
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def reset_password(request):
    email = request.data.get("email")
    new_password = request.data.get("new_password")
    confirm_password = request.data.get("confirm_password")

    saved_email = request.session.get("password_reset_email")
    is_verified = request.session.get("password_reset_verified", False)

    if not email or not new_password or not confirm_password:
        return Response(
            {"error": "email, new_password and confirm_password are required"},
            status=status.HTTP_400_BAD_REQUEST
        )

    if email != saved_email:
        return Response(
            {"error": "invalid password reset session"},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not is_verified:
        return Response(
            {"error": "otp verification is required before resetting password"},
            status=status.HTTP_400_BAD_REQUEST
        )

    if new_password != confirm_password:
        return Response(
            {"error": "passwords do not match"},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        validate_password(new_password)
    except DjangoValidationError as e:
        return Response(
            {"error": e.messages[0]},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        return Response(
            {"error": "user not found"},
            status=status.HTTP_404_NOT_FOUND
        )

    user.set_password(new_password)
    user.save()

    request.session.pop("password_reset_email", None)
    request.session.pop("password_reset_otp", None)
    request.session.pop("password_reset_expiry", None)
    request.session.pop("password_reset_verified", None)

    return Response(
        {"message": "password reset successful"},
        status=status.HTTP_200_OK
    )
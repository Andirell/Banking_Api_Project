from drf_spectacular.utils import inline_serializer
from rest_framework import serializers as drf_serializers
from transactions.serializers import TransactionSerializer
from wallets.serializers import WalletSerializer


# Common response/request shapes used across the project to avoid duplicate
# inline_serializer components in generated OpenAPI schema.
MessageResponse = inline_serializer(
    name="MessageResponse",
    fields={
        "message": drf_serializers.CharField(),
    },
)

ErrorResponse = inline_serializer(
    name="ErrorResponse",
    fields={
        "error": drf_serializers.CharField(),
    },
)

ValidationErrorResponse = inline_serializer(
    name="ValidationErrorResponse",
    fields={
        "errors": drf_serializers.DictField(),
    },
)

SignInRequest = inline_serializer(
    name="SignInRequest",
    fields={
        "email": drf_serializers.EmailField(),
        "password": drf_serializers.CharField(),
    },
)

SignInResponse = inline_serializer(
    name="SignInResponse",
    fields={
        "message": drf_serializers.CharField(),
        "access_token": drf_serializers.CharField(),
        "refresh_token": drf_serializers.CharField(),
    },
)

# Wallet and Transaction wrappers
WalletDetailResponse = inline_serializer(
    name="WalletDetailResponse",
    fields={
        "message": drf_serializers.CharField(),
        "data": WalletSerializer(),
    },
)

WalletCreateResponse = inline_serializer(
    name="WalletCreateResponse",
    fields={
        "message": drf_serializers.CharField(),
        "data": WalletSerializer(),
    },
)

WalletUpdateResponse = inline_serializer(
    name="WalletUpdateResponse",
    fields={
        "message": drf_serializers.CharField(),
        "data": WalletSerializer(),
    },
)

WalletAdminUpdateResponse = inline_serializer(
    name="WalletAdminUpdateResponse",
    fields={
        "message": drf_serializers.CharField(),
        "data": WalletSerializer(),
    },
)

TransactionActionResponse = inline_serializer(
    name="TransactionActionResponse",
    fields={
        "message": drf_serializers.CharField(),
        "balance": drf_serializers.DecimalField(max_digits=12, decimal_places=2),
        "transaction": TransactionSerializer(),
    },
)

# User request/response shapes used by multiple views
LogoutRequest = inline_serializer(
    name="LogoutRequest",
    fields={
        "refresh_token": drf_serializers.CharField(),
    },
)

ChangePasswordRequest = inline_serializer(
    name="ChangePasswordRequest",
    fields={
        "old_password": drf_serializers.CharField(),
        "new_password": drf_serializers.CharField(),
        "confirm_password": drf_serializers.CharField(),
    },
)

OTPRequest = inline_serializer(
    name="OTPRequest",
    fields={
        "otp": drf_serializers.CharField(),
    },
)

# Specific request shape used to verify OTP during signin (contains email + otp)
VerifySigninOTPRequest = inline_serializer(
    name="VerifySigninOTPRequest",
    fields={
        "email": drf_serializers.EmailField(),
        "otp": drf_serializers.CharField(),
    },
)

ForgotPasswordRequest = inline_serializer(
    name="ForgotPasswordRequest",
    fields={
        "email": drf_serializers.EmailField(),
    },
)

VerifyPasswordResetOTPRequest = inline_serializer(
    name="VerifyPasswordResetOTPRequest",
    fields={
        "email": drf_serializers.EmailField(),
        "otp": drf_serializers.CharField(),
    },
)

ResetPasswordRequest = inline_serializer(
    name="ResetPasswordRequest",
    fields={
        "email": drf_serializers.EmailField(),
        "new_password": drf_serializers.CharField(),
        "confirm_password": drf_serializers.CharField(),
    },
)

UpdateUserResponse = inline_serializer(
    name="UpdateUserResponse",
    fields={
        "message": drf_serializers.CharField(),
        "user": drf_serializers.DictField(),
    },
)

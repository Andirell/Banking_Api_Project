from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import User

# We use one message for any detail that is already taken (BVN or phone).
# If we said "this BVN is taken", people could use sign-up to check whose BVN is registered.
DUPLICATE_DETAILS_ERROR = "We couldn't register an account with these details. Contact support if you already have one."

MAX_KYC_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


def check_names_start_with_capital(attrs):
    first_name = attrs.get("first_name")
    last_name = attrs.get("last_name")

    if first_name and first_name[0].islower():
        raise serializers.ValidationError({"first_name": "Must start with a capital letter"})

    if last_name and last_name[0].islower():
        raise serializers.ValidationError({"last_name": "Must start with a capital letter"})


class UserSerializer(serializers.ModelSerializer):
    # Used for sign-up
    password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = (
            "first_name",
            "last_name",
            "email",
            "phone_number",
            "nationality",
            "date_of_birth",
            "address",
            "bvn",
            "password",
            "confirm_password",
        )
        # Turn off DRF's own "user with this bvn already exists" message.
        # Our validate() below gives one general message instead.
        extra_kwargs = {"bvn": {"validators": []}, "phone_number": {"validators": []}}

    def validate_bvn(self, value):
        if value and not (len(value) == 11 and value.isdigit()):
            raise serializers.ValidationError("BVN must be exactly 11 digits.")
        return value

    def validate(self, attrs):
        check_names_start_with_capital(attrs)

        password = attrs.get("password")
        if password != attrs.get("confirm_password"):
            raise serializers.ValidationError({"password": "Passwords do not match"})

        email = attrs.get("email")
        if email and User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError({"email": "A user with this email already exists"})

        bvn = attrs.get("bvn")
        phone_number = attrs.get("phone_number")
        bvn_taken = bvn and User.objects.filter(bvn=bvn).exists()
        phone_taken = phone_number and User.objects.filter(phone_number=phone_number).exists()
        if bvn_taken or phone_taken:
            raise serializers.ValidationError(DUPLICATE_DETAILS_ERROR)

        # Django's password rules (length, not too common, not all numbers...)
        validate_password(password)
        return attrs

    def create(self, validated_data):
        validated_data.pop("confirm_password")
        password = validated_data.pop("password")

        # Everyone who signs up is a customer. Staff are made in the admin.
        user = User(**validated_data, role="customer")
        user.set_password(password)
        user.save()
        return user


class UserProfileSerializer(serializers.ModelSerializer):
    # We never send the full BVN back, only the last 4 digits
    bvn = serializers.SerializerMethodField()

    @extend_schema_field(OpenApiTypes.STR)
    def get_bvn(self, obj):
        if not obj.bvn:
            return None
        return "*******" + obj.bvn[-4:]

    class Meta:
        model = User
        fields = (
            "id",
            "first_name",
            "last_name",
            "email",
            "phone_number",
            "nationality",
            "date_of_birth",
            "address",
            "bvn",
            "role",
            "is_active",
        )
        read_only_fields = fields


class UpdateUserSerializer(serializers.ModelSerializer):
    # The only fields a user can change on their own profile
    class Meta:
        model = User
        fields = (
            "first_name",
            "last_name",
            "phone_number",
            "nationality",
            "address",
        )

    def validate(self, attrs):
        check_names_start_with_capital(attrs)
        return attrs


class KYCSubmitSerializer(serializers.ModelSerializer):
    identity_document = serializers.ImageField(required=True)
    proof_of_address = serializers.ImageField(required=True)

    class Meta:
        model = User
        fields = ["identity_document", "proof_of_address"]

    def validate_identity_document(self, value):
        if value.size > MAX_KYC_FILE_SIZE:
            raise ValidationError("File size should not exceed 5MB.")
        return value

    def validate_proof_of_address(self, value):
        if value.size > MAX_KYC_FILE_SIZE:
            raise ValidationError("File size should not exceed 5MB.")
        return value

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from .models import User
from django.core.exceptions import ValidationError


DUPLICATE_DETAILS_ERROR = "We couldn't register an account with these details. Contact support if you already have one."


class UserSerializer(serializers.ModelSerializer):
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
        # DRF would add its own "user with this bvn already exists" check; the
        # generic duplicate check in validate() replaces it.
        extra_kwargs = {"bvn": {"validators": []}, "phone_number": {"validators": []}}

    def validate_bvn(self, value):
        if value and not (len(value) == 11 and value.isdigit()):
            raise serializers.ValidationError("BVN must be exactly 11 digits.")
        return value

    def validate(self, attrs):
        first_name = attrs.get("first_name")
        last_name = attrs.get("last_name")
        password = attrs.get("password")
        confirm_password = attrs.get("confirm_password")
        email = attrs.get("email")
        bvn = attrs.get("bvn")

        if first_name and first_name[0].islower():
            raise serializers.ValidationError(
                {"first_name": "Must start with a capital letter"}
            )

        if last_name and last_name[0].islower():
            raise serializers.ValidationError(
                {"last_name": "Must start with a capital letter"}
            )

        if password != confirm_password:
            raise serializers.ValidationError(
                {"password": "Passwords do not match"}
            )

        if email and User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError(
                {"email": "A user with this email already exists"}
            )

        # One answer for any taken identifier, so sign-up can't be used to
        # check whether a given BVN or phone number is registered.
        phone_number = attrs.get("phone_number")
        if (bvn and User.objects.filter(bvn=bvn).exists()) or (
            phone_number and User.objects.filter(phone_number=phone_number).exists()
        ):
            raise serializers.ValidationError(DUPLICATE_DETAILS_ERROR)

        validate_password(password)
        return attrs

    def create(self, validated_data):
        validated_data.pop("confirm_password")
        password = validated_data.pop("password")

        user = User(**validated_data, role="customer")
        user.set_password(password)
        user.save()
        return user


class UserProfileSerializer(serializers.ModelSerializer):
    # The full BVN is never sent back; the last 4 digits are enough to recognise it.
    bvn = serializers.SerializerMethodField()

    @extend_schema_field(OpenApiTypes.STR)
    def get_bvn(self, obj):
        return f"*******{obj.bvn[-4:]}" if obj.bvn else None

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
        first_name = attrs.get("first_name")
        last_name = attrs.get("last_name")

        if first_name and first_name[0].islower():
            raise serializers.ValidationError(
                {"first_name": "Must start with a capital letter"}
            )

        if last_name and last_name[0].islower():
            raise serializers.ValidationError(
                {"last_name": "Must start with a capital letter"}
            )

        return attrs
    
class KYCSubmitSerializer(serializers.ModelSerializer):
    identity_document = serializers.ImageField(required=True)
    proof_of_address = serializers.ImageField(required=True)

    class Meta:
        model = User
        fields = ['identity_document', 'proof_of_address']

    def validate_identity_document(self, value):
        # Add any validation for the document (file size, type, etc.)
        if value.size > 5 * 1024 * 1024:  # Limit file size to 5MB
            raise ValidationError("File size should not exceed 5MB.")
        return value

    def validate_proof_of_address(self, value):
        # Add any validation for the document (file size, type, etc.)
        if value.size > 5 * 1024 * 1024:  # Limit file size to 5MB
            raise ValidationError("File size should not exceed 5MB.")
        return value
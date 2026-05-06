from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from .models import User
from django.core.exceptions import ValidationError


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

        if email and User.objects.filter(email=email).exists():
            raise serializers.ValidationError(
                {"email": "A user with this email already exists"}
            )

        if bvn and User.objects.filter(bvn=bvn).exists():
            raise serializers.ValidationError(
                {"bvn": "A user with this BVN already exists"}
            )

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
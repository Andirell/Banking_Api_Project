from datetime import timedelta

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from .managers import UserManager
from .storage import private_kyc_storage


class User(AbstractUser):
    # We log in with email, so we don't need Django's username field
    username = None

    ROLE_CHOICES = (
        ('customer', 'Customer'),
        ('merchant', 'Merchant'),
        ('admin', 'Admin')
    )

    KYC_CHOICES = (
        ("pending", "Pending"),
        ("verified", "Verified"),
        ("rejected", "Rejected"),
    )

    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    nationality = models.TextField(blank=True, null=True)
    bvn = models.CharField(max_length=11, unique=True, blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    phone_number = models.CharField(max_length=15, unique=True, blank=True, null=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="customer")
    kyc_status = models.CharField(max_length=20, choices=KYC_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)

    # KYC documents. They are saved in private storage (no public URL).
    identity_document = models.ImageField(upload_to="kyc_documents/", storage=private_kyc_storage, blank=True, null=True)
    proof_of_address = models.ImageField(upload_to="kyc_documents/", storage=private_kyc_storage, blank=True, null=True)
    kyc_approved = models.BooleanField(default=False)
    kyc_rejection_reason = models.TextField(blank=True, null=True)

    # For locking the account after too many wrong passwords (see users/backends.py)
    failed_signin_attempts = models.PositiveSmallIntegerField(default=0)
    signin_locked_until = models.DateTimeField(blank=True, null=True)

    # Set when the customer closes their account. A closed account can't be reopened.
    closed_at = models.DateTimeField(blank=True, null=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ["first_name", "last_name"]

    objects = UserManager()

    class Meta(AbstractUser.Meta):
        constraints = [
            # "Ada@mail.com" and "ada@mail.com" must be the same account
            models.UniqueConstraint(Lower("email"), name="user_email_ci_unique"),
        ]

    def save(self, *args, **kwargs):
        # Always save emails in lowercase
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.email


class OTP(models.Model):
    # A one-time code we email to the user (for sign-in, password reset
    # or verification). See users/security.py for how they are used.
    PURPOSE_CHOICES = (
        ("signin", "Sign in"),
        ("password_reset", "Password reset"),
        ("verify", "Verification"),
    )

    user = models.ForeignKey('users.User', on_delete=models.CASCADE, related_name='otps')
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES, default="signin")
    code = models.CharField(max_length=10)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    # How many wrong guesses were made for this code
    attempts = models.PositiveSmallIntegerField(default=0)
    # Password reset only: when the code was checked (the reset happens in a second step)
    verified_at = models.DateTimeField(blank=True, null=True)

    def is_expired(self):
        return timezone.now() > self.expires_at

    @classmethod
    def create_for_user(cls, user, code, purpose="signin", lifetime_seconds=300):
        # Codes last 5 minutes by default
        expires = timezone.now() + timedelta(seconds=lifetime_seconds)
        return cls.objects.create(user=user, code=code, purpose=purpose, expires_at=expires)

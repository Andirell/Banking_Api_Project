from django.db import models
from django.contrib.auth.models import AbstractUser
from .managers import UserManager
from decimal import Decimal

class User(AbstractUser):
    username= None
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
    nationality = models.TextField( blank=True, null=True)
    bvn = models.CharField(max_length=11, unique=True, blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    phone_number = models.CharField(max_length=15, unique=True, blank=True, null=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="customer")
    kyc_status = models.CharField(max_length=20, choices=KYC_CHOICES, default="pending")
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    created_at = models.DateTimeField(auto_now_add=True)
     # KYC Document Fields
    identity_document = models.ImageField(upload_to="kyc_documents/", blank=True, null=True)  # User's ID document
    proof_of_address = models.ImageField(upload_to="kyc_documents/", blank=True, null=True)  # Address proof document
    # Admin KYC Approval Fields
    kyc_approved = models.BooleanField(default=False)  # Tracks whether KYC is approved
    kyc_rejection_reason = models.TextField(blank=True, null=True)  # Reason for rejection



    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ["first_name", "last_name"]

    objects: UserManager = UserManager()  # type: ignore

    def __str__(self):
        return self.email
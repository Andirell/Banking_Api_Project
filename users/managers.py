from django.contrib.auth.models import BaseUserManager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import User


class UserManager(BaseUserManager["User"]):
    def get_by_natural_key(self, username):
        # Emails are stored lowercased; match whatever case the user typed.
        return self.get(email__iexact=username)

    def create_user(self, email, first_name, last_name, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")

        email = self.normalize_email(email)
        user = self.model(
            email=email,
            first_name=first_name,
            last_name=last_name,
            **extra_fields
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, first_name, last_name, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", "admin")

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True")

        return self.create_user(email=email, first_name=first_name, last_name=last_name, password=password, **extra_fields )
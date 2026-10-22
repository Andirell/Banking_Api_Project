import logging

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from utils.mail import send_smtp_mail
from wallets.models import Wallet

from .models import User

logger = logging.getLogger(__name__)


@receiver(post_save, sender=User)
def send_mail_with_template(sender, instance, created, **kwargs):
    # Send the welcome email only after the new user is really saved
    # (on_commit waits until the database transaction has finished)
    if created:
        transaction.on_commit(lambda: send_welcome_email(instance))


def send_welcome_email(user):
    # If the email fails, the account still exists, so we just log the
    # error instead of making the whole sign-up fail.
    try:
        send_smtp_mail(
            subject="Welcome to Vampay.com",
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
            context={
                "header": f"{user.first_name} {user.last_name}",
                "description": "We are glad to have you bank with us.",
                "extra_info": "Let's get started.",
                # Only show the button if we have a website to link to
                "show_button": bool(settings.FRONTEND_URL),
                "button_text": "Get Started",
                "button_link": f"{settings.FRONTEND_URL}/onboarding",
            },
        )
    except Exception:
        logger.exception("Welcome email to user %s failed", user.pk)


@receiver(post_save, sender=User)
def create_wallet(sender, instance, created, **kwargs):
    # Every new user gets a wallet
    if created:
        Wallet.objects.create(user=instance)

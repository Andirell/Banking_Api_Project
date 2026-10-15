from .models import User
from django.db.models.signals import post_save
from django.dispatch import receiver #receiver helps listens to events and its a decorator
# from django.core.mail import send_mail
from utils.mail import send_smtp_mail
from .models import User
from wallets.models import Wallet
from django.conf import settings
from django.db import transaction
import logging

logger = logging.getLogger(__name__)



@receiver(post_save, sender=User)
def send_mail_with_template(sender, instance, created, **kwargs):
    if created:
        transaction.on_commit(lambda: _send_welcome_email(instance))


def _send_welcome_email(instance):
    # A welcome email is a courtesy: if the mail server is unreachable the
    # account still exists, so log the failure instead of failing sign-up.
    try:
        send_smtp_mail(
            subject="Welcome to Vampay.com",
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[instance.email],
            context={
                "header": f"{instance.first_name} {instance.last_name}",
                "description": "We are glad to have you bank with us.",
                "extra_info": "Let's get started.",
                # No button rather than a link to somewhere that doesn't exist.
                "show_button": bool(settings.FRONTEND_URL),
                "button_text": "Get Started",
                "button_link": f"{settings.FRONTEND_URL}/onboarding",
            }
        )
    except Exception:
        logger.exception("Welcome email to user %s failed", instance.pk)

@receiver(post_save, sender=User)
def create_wallet(sender, instance, created, **kwargs):
    if created:  # Only create a wallet when a new user is created
        Wallet.objects.create(user=instance)  # Create wallet for the user
    
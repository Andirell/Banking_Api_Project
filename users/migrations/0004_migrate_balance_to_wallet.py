"""Migrate balances from User.balance to Wallet.balance and remove User.balance

This migration creates missing Wallets for users and copies the numeric
balance into the new Wallet. It then removes the balance field from the
User model so Wallet becomes the single source of truth for balances.

Note: this is a data migration followed by a schema operation. It should be
applied carefully on production with a backup.
"""
from decimal import Decimal
from django.db import migrations


def forwards_func(apps, schema_editor):
    User = apps.get_model('users', 'User')
    Wallet = apps.get_model('wallets', 'Wallet')

    for user in User.objects.all():
        # For safety, only create a Wallet when one doesn't already exist
        try:
            wallet = Wallet.objects.filter(user_id=user.id).first()
        except Exception:
            wallet = None

        if wallet is None:
            # user.balance may not exist in some environments; use getattr
            bal = getattr(user, 'balance', None)
            if bal is None:
                bal = Decimal('0.00')
            Wallet.objects.create(user_id=user.id, balance=bal)
        else:
            # If wallet exists but balance is zero and user has a balance, copy it
            bal = getattr(user, 'balance', None)
            if bal is not None and wallet.balance == Decimal('0.00'):
                wallet.balance = bal
                wallet.save(update_fields=['balance'])


def reverse_func(apps, schema_editor):
    # Reverse: copy balance back from Wallet to User if User has no balance.
    User = apps.get_model('users', 'User')
    Wallet = apps.get_model('wallets', 'Wallet')

    for wallet in Wallet.objects.select_related('user').all():
        user = wallet.user
        # Only set User.balance if attribute exists; in migration revert it will
        # typically be present because this migration is expected to be reversed
        if hasattr(user, 'balance'):
            setattr(user, 'balance', wallet.balance)
            user.save(update_fields=['balance'])


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0003_user_identity_document_user_kyc_approved_and_more'),
        ('wallets', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(forwards_func, reverse_func),
        # Remove the User.balance field from the model schema
        migrations.RemoveField(
            model_name='user',
            name='balance',
        ),
    ]

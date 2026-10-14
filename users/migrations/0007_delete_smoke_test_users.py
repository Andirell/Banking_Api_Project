"""One-off cleanup of accounts created by deployment smoke tests (2026-10-14).

Only deletes users whose email matches smoke-*@example.com AND who have no
transactions, no loans and a zero wallet balance, so it can never remove a
real customer or financial history. Safe to run on any database (no-op when
nothing matches).
"""

from decimal import Decimal

from django.db import migrations
from django.db.models import Q


def delete_smoke_test_users(apps, schema_editor):
    User = apps.get_model("users", "User")
    Wallet = apps.get_model("wallets", "Wallet")
    Transaction = apps.get_model("transactions", "Transaction")
    LoanApplication = apps.get_model("loans", "LoanApplication")

    candidates = User.objects.filter(
        email__startswith="smoke-", email__endswith="@example.com", is_staff=False, is_superuser=False
    )
    with_history = set(
        Transaction.objects.filter(Q(sender__in=candidates) | Q(receiver__in=candidates))
        .values_list("sender_id", "receiver_id")
        .distinct()
        .iterator()
    )
    blocked = {user_id for pair in with_history for user_id in pair if user_id}
    blocked |= set(LoanApplication.objects.filter(user__in=candidates).values_list("user_id", flat=True))
    blocked |= set(
        Wallet.objects.filter(user__in=candidates).exclude(balance=Decimal("0")).values_list("user_id", flat=True)
    )

    doomed = candidates.exclude(pk__in=blocked)
    Wallet.objects.filter(user__in=doomed).delete()  # Wallet.user is PROTECT, so wallets go first
    doomed.delete()  # OTPs cascade; outstanding JWT records are SET_NULL


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0006_otp_attempts_otp_purpose_otp_verified_at_and_more"),
        ("wallets", "0003_alter_wallet_user"),
        ("transactions", "0004_transaction_funding_reference_and_more"),
        ("loans", "0002_alter_emi_loan_alter_loanapplication_user"),
        ("token_blacklist", "0013_alter_blacklistedtoken_options_and_more"),
    ]

    operations = [
        migrations.RunPython(delete_smoke_test_users, migrations.RunPython.noop),
    ]

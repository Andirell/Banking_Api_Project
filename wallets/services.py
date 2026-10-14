"""The only place wallet balances change.

Rules every caller relies on:
- Call these inside `transaction.atomic()`.
- Balances are written with F() expressions, never with a value read earlier,
  so a concurrent change can't be overwritten.
- `lock_wallets` locks rows in primary-key order so two transfers between the
  same pair of users can't deadlock.
"""

from django.db.models import F

from .models import Wallet


class InsufficientFunds(Exception):
    pass


def lock_wallets(*user_ids):
    """Lock and return the wallets of `user_ids`, in the order given."""
    wallets = Wallet.objects.select_for_update().filter(user_id__in=user_ids).order_by("pk")
    by_user = {wallet.user_id: wallet for wallet in wallets}
    missing = set(user_ids) - by_user.keys()
    if missing:
        raise Wallet.DoesNotExist(f"No wallet for user(s) {sorted(missing)}")
    return [by_user[user_id] for user_id in user_ids]


def credit(wallet, amount):
    Wallet.objects.filter(pk=wallet.pk).update(balance=F("balance") + amount)
    wallet.refresh_from_db(fields=["balance"])


def debit(wallet, amount):
    """Debit only if the *current* balance covers it; raise InsufficientFunds otherwise."""
    updated = Wallet.objects.filter(pk=wallet.pk, balance__gte=amount).update(balance=F("balance") - amount)
    if updated != 1:
        raise InsufficientFunds()
    wallet.refresh_from_db(fields=["balance"])

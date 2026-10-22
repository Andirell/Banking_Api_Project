# All wallet balance changes go through the functions in this file.
#
# How to use them:
#   with transaction.atomic():
#       sender_wallet, receiver_wallet = lock_wallets(sender.id, receiver.id)
#       debit(sender_wallet, amount)
#       credit(receiver_wallet, amount)
#
# Rules:
# - Always call them inside transaction.atomic().
# - We never do "wallet.balance = wallet.balance - amount; wallet.save()".
#   If two requests read the same balance at the same time, one of the changes
#   would be lost. Instead we let the database do the maths with F("balance").

from django.db.models import F

from .models import Wallet


class InsufficientFunds(Exception):
    pass


def lock_wallets(*user_ids):
    # Lock the wallets so no other request can change them until our
    # transaction finishes. We always lock in id order, so two transfers
    # between the same two people can't wait on each other forever (deadlock).
    wallets = Wallet.objects.select_for_update().filter(user_id__in=user_ids).order_by("pk")

    wallets_by_user = {}
    for wallet in wallets:
        wallets_by_user[wallet.user_id] = wallet

    for user_id in user_ids:
        if user_id not in wallets_by_user:
            missing = sorted(set(user_ids) - wallets_by_user.keys())
            raise Wallet.DoesNotExist(f"No wallet for user(s) {missing}")

    # Return them in the same order the caller asked for
    result = []
    for user_id in user_ids:
        result.append(wallets_by_user[user_id])
    return result


def check_amount_is_positive(amount):
    # A negative credit would take money away, and a negative debit would add
    # money without checking the balance. So zero or negative is never allowed.
    if amount <= 0:
        raise ValueError(f"amount must be positive, got {amount}")


def credit(wallet, amount):
    check_amount_is_positive(amount)
    Wallet.objects.filter(pk=wallet.pk).update(balance=F("balance") + amount)
    wallet.refresh_from_db(fields=["balance"])


def debit(wallet, amount):
    check_amount_is_positive(amount)

    # The "balance__gte" check and the subtraction happen in one query,
    # so the balance can never go below zero.
    rows_updated = Wallet.objects.filter(pk=wallet.pk, balance__gte=amount).update(balance=F("balance") - amount)
    if rows_updated != 1:
        raise InsufficientFunds()

    wallet.refresh_from_db(fields=["balance"])

import logging
from datetime import timedelta

from django.db import transaction as db_transaction
from django.utils import timezone

from transactions.models import Transaction

from .models import SuspiciousActivity

logger = logging.getLogger(__name__)


def flag_transaction_safely(transaction_obj):
    # Call this after every new transaction.
    #
    # If the fraud check crashes we don't want the payment to fail, but we also
    # don't want the crash to go unnoticed. So we save a "monitoring_failed" flag,
    # which staff will see in the flagged transactions list.
    try:
        # atomic() here makes a savepoint, so a database error inside the
        # fraud check can't break the payment's own transaction
        with db_transaction.atomic():
            return simple_flagTransaction(transaction_obj)
    except Exception:
        logger.exception("Fraud scoring failed for transaction %s", transaction_obj.pk)
        return SuspiciousActivity.objects.create(
            transaction=transaction_obj, risk_score=0.0, reason="monitoring_failed"
        )


def simple_flagTransaction(transaction_obj):
    # Simple fraud rules. Each rule that matches adds to the risk score.
    #   1. Amount over 10,000                         -> +0.9
    #   2. Transfer over 5,000                         -> +0.6
    #   3. 3 or more transfers from the sender in 1 hour -> +0.5
    #   4. First time sending to this receiver          -> +0.1
    # If the score is above 0 we save a SuspiciousActivity row.
    try:
        amount = float(transaction_obj.amount)
    except Exception:
        return None

    risk = 0.0
    reasons = []

    # Rule 1
    if amount > 10000:
        risk += 0.9
        reasons.append("amount_exceeds_10000")

    is_transfer = transaction_obj.transaction_type == "transfer"

    # Rule 2
    if is_transfer and amount > 5000:
        risk += 0.6
        reasons.append("high_transfer_amount")

    if is_transfer:
        # Rule 3
        one_hour_ago = timezone.now() - timedelta(hours=1)
        transfers_in_last_hour = Transaction.objects.filter(
            sender=transaction_obj.sender,
            transaction_type="transfer",
            created_at__gte=one_hour_ago,
        ).count()
        if transfers_in_last_hour >= 3:
            risk += 0.5
            reasons.append("high_transfer_velocity")

        # Rule 4
        sent_before = (
            Transaction.objects.filter(sender=transaction_obj.sender, receiver=transaction_obj.receiver)
            .exclude(id=transaction_obj.id)
            .exists()
        )
        if not sent_before:
            risk += 0.1
            reasons.append("new_receiver")

    if risk == 0:
        return None

    return SuspiciousActivity.objects.create(
        transaction=transaction_obj,
        risk_score=risk,
        reason=", ".join(reasons),
    )

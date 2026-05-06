from .models import SuspiciousActivity
from transactions.models import Transaction
from django.utils import timezone
from datetime import timedelta


def simple_flagTransaction(transaction_obj):
    """Run lightweight fraud checks on a Transaction and create a SuspiciousActivity when triggered.

    Rules implemented (simple heuristics for demo purposes):
    - High amount: amount > 10,000 => high risk
    - High transfer amount: transfers > 5,000 => medium risk
    - Velocity: more than 3 transfers from same sender in the last 60 minutes => medium risk
    - New receiver: sender has never sent to this receiver before => small risk (for transfers)

    Returns the SuspiciousActivity instance if created, otherwise None.
    """
    # convert amount to float for easy numeric checks
    try:
        amount = float(transaction_obj.amount)
    except Exception:
        return None

    risk = 0.0
    reasons = []

    # Rule 1: very large amount
    if amount > 10000:
        risk += 0.9
        reasons.append("amount_exceeds_10000")

    # Rule 2: large transfer amounts
    if transaction_obj.transaction_type == 'transfer' and amount > 5000:
        risk += 0.6
        reasons.append("high_transfer_amount")

    # Rule 3: velocity: number of transfers by same sender in the last 60 minutes
    if transaction_obj.transaction_type == 'transfer':
        one_hour_ago = timezone.now() - timedelta(hours=1)
        recent_count = Transaction.objects.filter(
            sender=transaction_obj.sender,
            transaction_type='transfer',
            created_at__gte=one_hour_ago,
        ).count()
        # if there are more than 3 transfers in the last hour, raise suspicion
        if recent_count >= 3:
            risk += 0.5
            reasons.append("high_transfer_velocity")

        # Rule 4: new receiver for this sender (first time sending to this receiver)
        prior = Transaction.objects.filter(sender=transaction_obj.sender, receiver=transaction_obj.receiver).exclude(id=transaction_obj.id).exists()
        if not prior:
            risk += 0.1
            reasons.append("new_receiver")

    if risk > 0:
        sa = SuspiciousActivity.objects.create(
            transaction=transaction_obj,
            risk_score=risk,
            reason=", ".join(reasons),
        )
        return sa

    return None

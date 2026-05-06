from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from .models import EMI


def create_emis_for_loan(loan):
    """Create equal-installment EMIs for a loan.

    This uses a simple equal-division approach and schedules EMIs every 30 days.
    """
    amount = Decimal(loan.amount)
    months = int(loan.duration_months)
    if months <= 0:
        return []

    # compute monthly payment (rounded to 2 decimals)
    monthly = (amount / months).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    emis = []
    for i in range(1, months + 1):
        due = date.today() + timedelta(days=30 * i)
        emi = EMI.objects.create(loan=loan, due_date=due, amount=monthly)
        emis.append(emi)

    return emis

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from .models import EMI


def create_emis_for_loan(loan):
    # Split the loan into equal monthly payments (EMIs), one every 30 days.
    # Example: 1,200 over 12 months -> 12 payments of 100.
    amount = Decimal(loan.amount)
    months = int(loan.duration_months)
    if months <= 0:
        return []

    monthly_payment = (amount / months).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    emis = []
    for month in range(1, months + 1):
        due_date = date.today() + timedelta(days=30 * month)
        emi = EMI.objects.create(loan=loan, due_date=due_date, amount=monthly_payment)
        emis.append(emi)

    return emis

from django.db import models


class SuspiciousActivity(models.Model):
    # One row for each transaction our fraud rules flagged (see analytics/utils.py)
    transaction = models.ForeignKey('transactions.Transaction', on_delete=models.PROTECT, related_name='suspicious_flags')
    risk_score = models.FloatField()
    reason = models.TextField()
    flagged_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Flag for tx {self.transaction_id} - score {self.risk_score}"

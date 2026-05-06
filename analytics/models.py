from django.db import models
from django.conf import settings

class SuspiciousActivity(models.Model):
    transaction = models.ForeignKey('transactions.Transaction', on_delete=models.CASCADE, related_name='suspicious_flags')
    risk_score = models.FloatField()
    reason = models.TextField()
    flagged_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        # use transaction.id to avoid referencing an unknown attribute
        return f"Flag for tx {getattr(self.transaction, 'id', None)} - score {self.risk_score}"

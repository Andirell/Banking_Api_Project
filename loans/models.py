from django.db import models
from django.conf import settings
from decimal import Decimal


class LoanApplication(models.Model):
	STATUS_CHOICES = (
		("pending", "Pending"),
		("approved", "Approved"),
		("rejected", "Rejected"),
	)

	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="loan_applications")
	amount = models.DecimalField(max_digits=12, decimal_places=2)
	duration_months = models.IntegerField()
	status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
	reason = models.TextField(blank=True, null=True)
	created_at = models.DateTimeField(auto_now_add=True)

	def __str__(self):
		# use getattr to keep static type-checkers happy about dynamic model attrs
		return f"Loan {getattr(self, 'id', 'n/a')} - {self.user} - {self.status}"


class EMI(models.Model):
	loan = models.ForeignKey(LoanApplication, on_delete=models.CASCADE, related_name="emis")
	due_date = models.DateField()
	amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
	paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
	is_paid = models.BooleanField(default=False)

	def __str__(self):
		# access loan id via getattr to avoid static-analysis complaints
		loan_id = getattr(getattr(self, 'loan', None), 'id', 'n/a')
		return f"EMI {getattr(self, 'id', 'n/a')} for Loan {loan_id} - due {self.due_date}"

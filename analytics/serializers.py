from rest_framework import serializers
from .models import SuspiciousActivity

class SuspiciousActivitySerializer(serializers.ModelSerializer):
    class Meta:
        model = SuspiciousActivity
        fields = ['id', 'transaction', 'risk_score', 'reason', 'flagged_at']

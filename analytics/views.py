from django.utils.dateparse import parse_date
from rest_framework import generics, permissions
from rest_framework.exceptions import ValidationError

from .models import SuspiciousActivity
from .serializers import SuspiciousActivitySerializer


class FlaggedTransactionsListAPIView(generics.ListAPIView):
    # Staff only. Lists flagged transactions, newest first.
    # Optional filters in the URL:
    #   ?risk_min=0.5&risk_max=1&from_date=2026-01-01&to_date=2026-01-31
    permission_classes = [permissions.IsAdminUser]
    serializer_class = SuspiciousActivitySerializer

    def get_queryset(self):
        flags = SuspiciousActivity.objects.all().order_by("-flagged_at")
        params = self.request.GET

        risk_min = params.get("risk_min")
        if risk_min:
            flags = flags.filter(risk_score__gte=read_number(risk_min, "risk_min"))

        risk_max = params.get("risk_max")
        if risk_max:
            flags = flags.filter(risk_score__lte=read_number(risk_max, "risk_max"))

        from_date = params.get("from_date")
        if from_date:
            flags = flags.filter(flagged_at__date__gte=read_date(from_date, "from_date"))

        to_date = params.get("to_date")
        if to_date:
            flags = flags.filter(flagged_at__date__lte=read_date(to_date, "to_date"))

        return flags


# A bad filter value returns a 400 error instead of crashing or being ignored

def read_number(text, name):
    try:
        return float(text)
    except ValueError:
        raise ValidationError({name: f"invalid value {text!r}"})


def read_date(text, name):
    try:
        value = parse_date(text)  # expects YYYY-MM-DD
    except ValueError:
        value = None
    if value is None:
        raise ValidationError({name: f"invalid value {text!r}"})
    return value

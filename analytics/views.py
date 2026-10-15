from django.utils.dateparse import parse_date
from rest_framework import generics, permissions
from rest_framework.exceptions import ValidationError
from .models import SuspiciousActivity
from .serializers import SuspiciousActivitySerializer

class FlaggedTransactionsListAPIView(generics.ListAPIView):
    permission_classes = [permissions.IsAdminUser]
    # We set serializer and then compute queryset dynamically in get_queryset so
    # admin users can filter by risk_score and date ranges using query params.
    serializer_class = SuspiciousActivitySerializer

    def get_queryset(self):
        qs = SuspiciousActivity.objects.all().order_by('-flagged_at')
        # Optional filters: risk_min, risk_max, from_date (YYYY-MM-DD), to_date (YYYY-MM-DD).
        # A bad value is a client error, not a crash or a silently ignored filter.
        filters = {
            "risk_min": ("risk_score__gte", _parse_float),
            "risk_max": ("risk_score__lte", _parse_float),
            "from_date": ("flagged_at__date__gte", parse_date),
            "to_date": ("flagged_at__date__lte", parse_date),
        }
        for param, (lookup, parse) in filters.items():
            raw = self.request.GET.get(param)
            if raw in (None, ""):
                continue
            try:
                value = parse(raw)
            except ValueError:
                value = None
            if value is None:
                raise ValidationError({param: f"invalid value {raw!r}"})
            qs = qs.filter(**{lookup: value})

        return qs


def _parse_float(raw):
    return float(raw)

from rest_framework import generics, permissions
from .models import SuspiciousActivity
from .serializers import SuspiciousActivitySerializer

class FlaggedTransactionsListAPIView(generics.ListAPIView):
    permission_classes = [permissions.IsAdminUser]
    # We set serializer and then compute queryset dynamically in get_queryset so
    # admin users can filter by risk_score and date ranges using query params.
    serializer_class = SuspiciousActivitySerializer

    def get_queryset(self):
        qs = SuspiciousActivity.objects.all().order_by('-flagged_at')
        # Optional filters: risk_min, risk_max, from_date (YYYY-MM-DD), to_date (YYYY-MM-DD)
        risk_min = self.request.GET.get('risk_min')
        risk_max = self.request.GET.get('risk_max')
        from_date = self.request.GET.get('from_date')
        to_date = self.request.GET.get('to_date')

        if risk_min is not None:
            try:
                qs = qs.filter(risk_score__gte=float(risk_min))
            except ValueError:
                pass

        if risk_max is not None:
            try:
                qs = qs.filter(risk_score__lte=float(risk_max))
            except ValueError:
                pass

        if from_date:
            qs = qs.filter(flagged_at__date__gte=from_date)

        if to_date:
            qs = qs.filter(flagged_at__date__lte=to_date)

        return qs

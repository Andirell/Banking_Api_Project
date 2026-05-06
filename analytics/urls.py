from django.urls import path
from .views import FlaggedTransactionsListAPIView

urlpatterns = [
    path('flagged-transactions/', FlaggedTransactionsListAPIView.as_view(), name='flagged_transactions'),
]

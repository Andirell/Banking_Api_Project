# transactions/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    DepositAPIView,
    WithdrawAPIView,
    TransferAPIView,
    TransactionViewSet,
)

router = DefaultRouter()
router.register(r'', TransactionViewSet, basename='transaction')

urlpatterns = [
    path('deposit/', DepositAPIView.as_view(), name='deposit'),
    path('withdraw/', WithdrawAPIView.as_view(), name='withdraw'),
    # alias to match project guide: /transactions/send/
    path('send/', TransferAPIView.as_view(), name='send'),
    path('', include(router.urls)),
]
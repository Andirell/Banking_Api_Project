from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import DepositAPIView, TransactionViewSet, TransferAPIView, WithdrawAPIView

# The router gives us GET /transactions/ (list) and GET /transactions/<id>/ (detail)
router = DefaultRouter()
router.register(r"", TransactionViewSet, basename="transaction")

urlpatterns = [
    path("deposit/", DepositAPIView.as_view(), name="deposit"),
    path("withdraw/", WithdrawAPIView.as_view(), name="withdraw"),
    path("send/", TransferAPIView.as_view(), name="send"),
    path("", include(router.urls)),
]

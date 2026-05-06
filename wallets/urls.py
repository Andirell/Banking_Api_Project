from django.urls import path
from .views import WalletAdminUpdateAPIView, WalletDetailAPIView, WalletCreateAPIView, WalletUpdateAPIView

urlpatterns = [
    path('details/', WalletDetailAPIView.as_view(), name='wallet_detail'),
    path('create/', WalletCreateAPIView.as_view(), name='wallet_create'),
    path('update/', WalletUpdateAPIView.as_view(), name='wallet_update'),
    path('admin/update/<int:pk>/', WalletAdminUpdateAPIView.as_view(), name='wallet_admin_update'),
]
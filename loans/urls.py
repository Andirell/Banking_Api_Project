from django.urls import path
from .views import (
    LoanApplyAPIView,
    LoanStatusAPIView,
    admin_approve_loan,
    AdminLoanListAPIView,
    EMIListAPIView,
    EMIPayAPIView,
)

urlpatterns = [
    path('apply/', LoanApplyAPIView.as_view(), name='loan_apply'),
    path('status/<int:pk>/', LoanStatusAPIView.as_view(), name='loan_status'),
    path('admin/approve/', admin_approve_loan, name='loan_admin_approve'),
    path('admin/list/', AdminLoanListAPIView.as_view(), name='loan_admin_list'),
    path('emis/', EMIListAPIView.as_view(), name='emi_list'),
    path('emis/<int:emi_id>/pay/', EMIPayAPIView.as_view(), name='emi_pay'),
]

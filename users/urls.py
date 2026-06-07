from django.urls import path
from . import views

urlpatterns = [
    path("signup/", views.signup, name="signup"),
    path("signin/", views.signin, name="signin"),
    path("logout/", views.logout_view, name="logout"),
    path("me/", views.get_me, name="get_me"),
    path('kyc/submit/', views.KYCSubmitAPIView.as_view(), name='kyc_submit'),  # User submits KYC
    path('kyc/admin/approve/<int:user_id>/', views.KYCAdminApprovalAPIView.as_view(), name='kyc_admin_approve'),  # Admin approves/rejects KYC


    path("update/", views.update_user, name="update_user"),
    path("delete/", views.delete_user, name="delete_user"),
    path("change-password/", views.change_password, name="change_password"),

    path("block/<int:id>/", views.block_user, name="block_user"),
    path("unblock/<int:id>/", views.unblock_user, name="unblock_user"),

    path("send-otp/", views.send_otp_view, name="send_otp"),
    path("verify-otp/", views.verify_otp_view, name="verify_otp"),
    # Sign-in OTP verification (no authentication required; used after /signin/)
    path("verify-signin-otp/", views.verify_signin_otp, name="verify_signin_otp"),

    path("request-password-reset/", views.request_password_reset, name="request_password_reset"),
    path("verify-password-reset-otp/", views.verify_password_reset_otp, name="verify_password_reset_otp"),
    path("reset-password/", views.reset_password, name="reset_password"),
]
from django.urls import path

from .accounts import CustomerProfileView, CustomerRegistrationView
from .views import LogoutView, UserProfileView
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView


class StaffTokenObtainPairView(TokenObtainPairView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_login"


class StaffTokenRefreshView(TokenRefreshView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_refresh"


urlpatterns = [
    path("login/", StaffTokenObtainPairView.as_view(), name="auth-login"),
    path("refresh/", StaffTokenRefreshView.as_view(), name="auth-refresh"),
    path("register/", CustomerRegistrationView.as_view(), name="auth-register"),
    path("me/", UserProfileView.as_view(), name="auth-me"),
    path("profile/", CustomerProfileView.as_view(), name="auth-profile"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
]

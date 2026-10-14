from django.urls import path

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
    path("me/", UserProfileView.as_view(), name="auth-me"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
]

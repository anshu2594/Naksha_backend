from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.catalog.views import CategoryViewSet, ProductViewSet
from apps.commerce.views import (
    CartView,
    CartQuoteView,
    GuestSessionView,
    OrderCancelView,
    OrderDetailView,
    OrderListCreateView,
    WishlistToggleView,
    WishlistView,
)
from apps.commerce.payments import (
    RazorpayCheckoutView,
    RazorpayVerifyView,
    RazorpayWebhookView,
)

from django.views.decorators.http import require_GET


@require_GET
def service_status(request):
    return JsonResponse({"service": "Naksha API", "status": "ok"})


@require_GET
def health_check(request):
    return JsonResponse({"status": "ok"})

router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("products", ProductViewSet, basename="product")

urlpatterns = [
    path("", service_status, name="service-status"),
    path("health/", health_check, name="health-check"),
    path("admin/", admin.site.urls),
    path("api/v1/", include(router.urls)),
    path("api/schema/", SpectacularAPIView.as_view(), name="openapi-schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="openapi-schema"),
        name="swagger-ui",
    ),
    path("api/v1/auth/", include("apps.backoffice.auth_urls")),
    path("api/v1/admin/", include("apps.backoffice.urls")),
    path("api/v1/session/", GuestSessionView.as_view(), name="guest-session"),
    path("api/v1/cart", CartView.as_view(), name="cart"),
    path("api/v1/cart/", CartView.as_view(), name="cart-slash"),
    path("api/v1/cart/quote/", CartQuoteView.as_view(), name="cart-quote"),
    path("api/v1/cart/items", CartView.as_view(), name="cart-items"),
    path("api/v1/cart/items/<int:item_id>", CartView.as_view(), name="cart-item"),
    path("api/v1/wishlist", WishlistView.as_view(), name="wishlist"),
    path("api/v1/wishlist/", WishlistView.as_view(), name="wishlist-slash"),
    path(
        "api/v1/wishlist/toggle/<str:product_id>",
        WishlistToggleView.as_view(),
        name="wishlist-toggle",
    ),
    path("api/v1/orders", OrderListCreateView.as_view(), name="orders"),
    path("api/v1/orders/", OrderListCreateView.as_view(), name="orders-slash"),
    path(
        "api/v1/orders/<str:order_number>",
        OrderDetailView.as_view(),
        name="order-detail",
    ),
    path(
        "api/v1/orders/<str:order_number>/cancel",
        OrderCancelView.as_view(),
        name="order-cancel",
    ),
    path(
        "api/v1/orders/<str:order_number>/payment/",
        RazorpayCheckoutView.as_view(),
        name="razorpay-checkout",
    ),
    path(
        "api/v1/orders/<str:order_number>/payment/verify/",
        RazorpayVerifyView.as_view(),
        name="razorpay-verify",
    ),
    path(
        "api/v1/webhooks/razorpay/",
        RazorpayWebhookView.as_view(),
        name="razorpay-webhook",
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

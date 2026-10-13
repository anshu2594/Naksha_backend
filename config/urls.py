from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.catalog.views import CategoryViewSet, ProductViewSet
from apps.commerce.views import (
    CartView,
    GuestSessionView,
    OrderCancelView,
    OrderDetailView,
    OrderListCreateView,
    WishlistToggleView,
    WishlistView,
)

router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("products", ProductViewSet, basename="product")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include(router.urls)),
    path("api/v1/session/", GuestSessionView.as_view(), name="guest-session"),
    path("api/v1/cart", CartView.as_view(), name="cart"),
    path("api/v1/cart/", CartView.as_view(), name="cart-slash"),
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
]

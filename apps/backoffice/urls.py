from django.urls import path
from .views import (
    AdminSessionView,
    CategoryDetailView,
    CategoryListCreateView,
    CustomerListView,
    DashboardView,
    OfferDetailView,
    OfferListCreateView,
    OrderDetailAdminView,
    OrderListAdminView,
    OrderRefundView,
    OrderStatusView,
    ProductDetailAdminView,
    ProductImageDetailView,
    ProductImageListCreateView,
    ProductListCreateView,
)

urlpatterns = [
    path("session/", AdminSessionView.as_view(), name="admin-session"),
    path("dashboard/", DashboardView.as_view(), name="admin-dashboard"),
    path("categories/", CategoryListCreateView.as_view(), name="admin-categories"),
    path(
        "categories/<slug:pk>/",
        CategoryDetailView.as_view(),
        name="admin-category-detail",
    ),
    path("products/", ProductListCreateView.as_view(), name="admin-products"),
    path(
        "products/<str:pk>/",
        ProductDetailAdminView.as_view(),
        name="admin-product-detail",
    ),
    path(
        "products/<str:product_id>/images/",
        ProductImageListCreateView.as_view(),
        name="admin-product-images",
    ),
    path(
        "products/<str:product_id>/images/<int:image_id>/",
        ProductImageDetailView.as_view(),
        name="admin-product-image-detail",
    ),
    path("customers/", CustomerListView.as_view(), name="admin-customers"),
    path("orders/", OrderListAdminView.as_view(), name="admin-orders"),
    path(
        "orders/<str:order_number>/",
        OrderDetailAdminView.as_view(),
        name="admin-order-detail",
    ),
    path(
        "orders/<str:order_number>/status/",
        OrderStatusView.as_view(),
        name="admin-order-status",
    ),
    path(
        "orders/<str:order_number>/refunds/",
        OrderRefundView.as_view(),
        name="admin-order-refund",
    ),
    path("offers/", OfferListCreateView.as_view(), name="admin-offers"),
    path(
        "offers/<int:pk>/",
        OfferDetailView.as_view(),
        name="admin-offer-detail",
    ),
]

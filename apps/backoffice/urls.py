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
    PaymentDetailAdminView,
    PaymentListAdminView,
    ProductDetailAdminView,
    ProductImageDetailView,
    ProductImageListCreateView,
    ProductListCreateView,
    RegisteredCustomerDetailView,
    RegisteredCustomerListView,
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
    path(
        "customers/accounts/",
        RegisteredCustomerListView.as_view(),
        name="admin-registered-customers",
    ),
    path(
        "customers/accounts/<int:customer_id>/",
        RegisteredCustomerDetailView.as_view(),
        name="admin-registered-customer-detail",
    ),
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
    path("payments/", PaymentListAdminView.as_view(), name="admin-payments"),
    path(
        "payments/<int:payment_id>/",
        PaymentDetailAdminView.as_view(),
        name="admin-payment-detail",
    ),
    path("offers/", OfferListCreateView.as_view(), name="admin-offers"),
    path(
        "offers/<int:pk>/",
        OfferDetailView.as_view(),
        name="admin-offer-detail",
    ),
]

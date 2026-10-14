from decimal import Decimal

from django.db import transaction
from django.db.models import Count, OuterRef, Q, Subquery, Sum
from django.db.models.deletion import ProtectedError
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from django.utils import timezone
from uuid import UUID
from rest_framework import generics, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import LimitOffsetPagination
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.catalog.models import Category, Product, ProductImage
from apps.commerce.inventory import release_order_inventory
from apps.commerce.models import (
    DiscountOffer,
    GuestSession,
    Order,
    OrderStatusHistory,
    PaymentRefund,
    RazorpayPayment,
)
from apps.commerce.serializers import OrderSerializer

from .serializers import (
    AdminOrderSerializer,
    CategoryAdminSerializer,
    CustomerSerializer,
    DiscountOfferSerializer,
    OrderDetailAdminSerializer,
    OrderStatusUpdateSerializer,
    PaymentRefundSerializer,
    ProductAdminSerializer,
    ProductImageSerializer,
    ProductImageUploadSerializer,
    RefundCreateSerializer,
)


class Conflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This operation conflicts with the current resource state."
    default_code = "conflict"


class StaffAPIView(APIView):
    authentication_classes = [JWTAuthentication, SessionAuthentication]
    permission_classes = [IsAdminUser]


class StaffListCreateAPIView(generics.ListCreateAPIView):
    authentication_classes = [JWTAuthentication, SessionAuthentication]
    permission_classes = [IsAdminUser]


class StaffDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    authentication_classes = [JWTAuthentication, SessionAuthentication]
    permission_classes = [IsAdminUser]


class UserProfileView(APIView):
    authentication_classes = [JWTAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        return Response(
            {
                "id": user.pk,
                "username": user.get_username(),
                "email": user.email,
                "role": "staff" if user.is_staff else "customer",
                "isStaff": user.is_staff,
            }
        )


class LogoutView(APIView):
    authentication_classes = [JWTAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        token_value = request.data.get("refresh", "")
        if not isinstance(token_value, str) or not token_value:
            raise ValidationError({"refresh": "A refresh token is required."})
        try:
            token = RefreshToken(token_value)
            if str(token.get("user_id")) != str(request.user.pk):
                raise ValidationError({"refresh": "This token belongs to another user."})
            token.blacklist()
        except TokenError as exc:
            raise ValidationError({"refresh": "Refresh token is invalid or expired."}) from exc
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminSessionView(StaffAPIView):
    def get(self, request):
        return Response(
            {"isStaff": True, "username": request.user.get_username(), "csrfToken": get_token(request)}
        )


class DashboardView(StaffAPIView):
    def get(self, request):
        orders = Order.objects.all()
        paid_states = [
            Order.PaymentStatus.PAID,
            Order.PaymentStatus.PARTIALLY_REFUNDED,
            Order.PaymentStatus.REFUNDED,
        ]
        gross_paid = orders.filter(payment_status__in=paid_states).aggregate(
            total=Sum("total")
        )["total"] or Decimal("0.00")
        refunds = PaymentRefund.objects.filter(
            status=PaymentRefund.Status.PROCESSED
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        return Response(
            {
                "orders": orders.count(),
                "pendingOrders": orders.filter(status=Order.Status.PENDING).count(),
                "customers": GuestSession.objects.filter(orders__isnull=False)
                .distinct()
                .count(),
                "activeProducts": Product.objects.filter(is_active=True).count(),
                "revenue": str(max(Decimal("0.00"), gross_paid - refunds)),
                "asOf": timezone.now(),
            }
        )


class CategoryListCreateView(StaffListCreateAPIView):
    queryset = Category.objects.all()
    serializer_class = CategoryAdminSerializer


class CategoryDetailView(StaffDetailAPIView):
    queryset = Category.objects.all()
    serializer_class = CategoryAdminSerializer

    def perform_destroy(self, instance):
        try:
            instance.delete()
        except ProtectedError as exc:
            raise Conflict("Categories with products cannot be deleted.") from exc


class ProductListCreateView(StaffListCreateAPIView):
    serializer_class = ProductAdminSerializer

    def get_queryset(self):
        queryset = Product.objects.select_related("category").prefetch_related(
            "uploaded_images"
        )
        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(slug__icontains=search)
                | Q(sku__icontains=search)
            )
        category = self.request.query_params.get("category")
        if category:
            queryset = queryset.filter(category_id=category)
        active = self.request.query_params.get("active")
        if active in {"true", "false"}:
            queryset = queryset.filter(is_active=active == "true")
        return queryset


class ProductDetailAdminView(StaffDetailAPIView):
    queryset = Product.objects.select_related("category").prefetch_related(
        "uploaded_images"
    )
    serializer_class = ProductAdminSerializer

    def perform_destroy(self, instance):
        image_paths = list(instance.uploaded_images.values_list("image", flat=True))
        try:
            instance.delete()
        except ProtectedError as exc:
            raise Conflict(
                "Products referenced by a cart cannot be deleted; deactivate them instead."
            ) from exc
        for image_path in image_paths:
            ProductImage._meta.get_field("image").storage.delete(image_path)


class ProductImageListCreateView(StaffAPIView):
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request, product_id):
        product = get_object_or_404(Product, pk=product_id)
        return Response(
            ProductImageSerializer(
                product.uploaded_images.all(), many=True, context={"request": request}
            ).data
        )

    def post(self, request, product_id):
        product = get_object_or_404(Product, pk=product_id)
        files = request.FILES.getlist("images") or request.FILES.getlist("image")
        if not files:
            raise ValidationError({"images": "Upload at least one image file."})

        validated = []
        for file_obj in files:
            serializer = ProductImageUploadSerializer(
                data={
                    "image": file_obj,
                    "altText": request.data.get("altText", ""),
                    "sortOrder": request.data.get("sortOrder", 0),
                }
            )
            serializer.is_valid(raise_exception=True)
            validated.append(serializer.validated_data)

        with transaction.atomic():
            images = [
                ProductImage.objects.create(product=product, **values)
                for values in validated
            ]
        return Response(
            ProductImageSerializer(
                images, many=True, context={"request": request}
            ).data,
            status=status.HTTP_201_CREATED,
        )


class ProductImageDetailView(StaffAPIView):
    def delete(self, request, product_id, image_id):
        image = get_object_or_404(
            ProductImage, pk=image_id, product_id=product_id
        )
        image.image.delete(save=False)
        image.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CustomerListView(StaffAPIView):
    pagination_class = LimitOffsetPagination

    def get(self, request):
        recent_order = Order.objects.filter(guest_id=OuterRef("pk")).order_by(
            "-created_at"
        )
        guests = GuestSession.objects.annotate(
            order_count=Count("orders", distinct=True),
            paid_total=Sum(
                "orders__total",
                filter=Q(
                    orders__payment_status__in=[
                        Order.PaymentStatus.PAID,
                        Order.PaymentStatus.PARTIALLY_REFUNDED,
                        Order.PaymentStatus.REFUNDED,
                    ]
                ),
            ),
            latest_order_at=Subquery(recent_order.values("created_at")[:1]),
            latest_name=Subquery(
                recent_order.values("shipping_address__fullName")[:1]
            ),
            latest_phone=Subquery(recent_order.values("shipping_address__phone")[:1]),
        ).filter(orders__isnull=False)
        search = request.query_params.get("search", "").strip().casefold()
        if search:
            match = Q(latest_name__icontains=search) | Q(latest_phone__icontains=search)
            try:
                match |= Q(id=UUID(search))
            except ValueError:
                pass
            guests = guests.filter(match)
        customers = [
            {
                "id": guest.id,
                "fullName": guest.latest_name or "Guest customer",
                "phone": guest.latest_phone or "",
                "latestOrderAt": guest.latest_order_at,
                "orderCount": guest.order_count,
                "paidTotal": guest.paid_total or Decimal("0.00"),
            }
            for guest in guests.order_by("-latest_order_at")
        ]
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(customers, request, view=self)
        return paginator.get_paginated_response(CustomerSerializer(page, many=True).data)


class OrderListAdminView(StaffAPIView):
    pagination_class = LimitOffsetPagination

    def get(self, request):
        orders = Order.objects.select_related("guest").prefetch_related("items")
        order_status = request.query_params.get("status")
        payment_status = request.query_params.get("paymentStatus")
        search = request.query_params.get("search", "").strip()
        if order_status:
            orders = orders.filter(status=order_status.upper())
        if payment_status:
            orders = orders.filter(payment_status=payment_status.lower())
        if search:
            orders = orders.filter(
                Q(order_number__icontains=search)
                | Q(shipping_address__fullName__icontains=search)
                | Q(shipping_address__phone__icontains=search)
                | Q(guest_id__icontains=search)
            )
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(orders, request, view=self)
        return paginator.get_paginated_response(
            AdminOrderSerializer(page, many=True, context={"request": request}).data
        )


class OrderDetailAdminView(StaffAPIView):
    def get(self, request, order_number):
        order = get_object_or_404(
            Order.objects.prefetch_related("items", "status_history__changed_by"),
            order_number=order_number,
        )
        return Response(
            OrderDetailAdminSerializer(order, context={"request": request}).data
        )


class OrderStatusView(StaffAPIView):
    def patch(self, request, order_number):
        serializer = OrderStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target_status = serializer.validated_data["status"]
        note = serializer.validated_data.get("note", "")

        with transaction.atomic():
            order = get_object_or_404(
                Order.objects.select_for_update().prefetch_related("items"),
                order_number=order_number,
            )
            if target_status == order.status:
                return Response(OrderSerializer(order).data)

            transitions = {
                Order.Status.PENDING: {Order.Status.PROCESSING, Order.Status.CANCELLED},
                Order.Status.PROCESSING: {Order.Status.SHIPPED, Order.Status.CANCELLED},
                Order.Status.SHIPPED: {Order.Status.DELIVERED},
                Order.Status.DELIVERED: set(),
                Order.Status.CANCELLED: set(),
            }
            if target_status not in transitions[order.status]:
                raise Conflict(
                    f"An order cannot move from {order.status} to {target_status}."
                )
            if (
                target_status
                in {
                    Order.Status.PROCESSING,
                    Order.Status.SHIPPED,
                    Order.Status.DELIVERED,
                }
                and order.payment_method != Order.PaymentMethod.COD
                and order.payment_status
                not in {
                    Order.PaymentStatus.PAID,
                    Order.PaymentStatus.PARTIALLY_REFUNDED,
                }
            ):
                raise Conflict("Online orders must be paid before fulfillment.")
            if target_status == Order.Status.CANCELLED:
                if order.payment_status in {
                    Order.PaymentStatus.PAID,
                    Order.PaymentStatus.PARTIALLY_REFUNDED,
                }:
                    raise Conflict("Refund paid orders before cancelling them.")
                if order.payments.filter(
                    status=RazorpayPayment.Status.CREATED
                ).exists():
                    raise Conflict(
                        "Resolve the active payment attempt before cancelling."
                    )
                release_order_inventory(order)

            old_status = order.status
            order.status = target_status
            order.save(update_fields=["status", "updated_at"])
            OrderStatusHistory.objects.create(
                order=order,
                old_status=old_status,
                new_status=target_status,
                changed_by=request.user,
                note=note,
            )
        return Response(OrderSerializer(order).data)


class OfferListCreateView(StaffListCreateAPIView):
    queryset = DiscountOffer.objects.all()
    serializer_class = DiscountOfferSerializer


class OfferDetailView(StaffDetailAPIView):
    queryset = DiscountOffer.objects.all()
    serializer_class = DiscountOfferSerializer


class OrderRefundView(StaffAPIView):
    def post(self, request, order_number):
        order = get_object_or_404(
            Order.objects.prefetch_related("refunds"), order_number=order_number
        )
        serializer = RefundCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        idempotency_key = request.headers.get("Idempotency-Key", "").strip()
        if not idempotency_key:
            raise ValidationError(
                {"Idempotency-Key": "This header is required for refunds."}
            )
        from apps.commerce.payments import create_refund

        refund, created = create_refund(
            order=order,
            amount=serializer.validated_data["amount"],
            idempotency_key=idempotency_key,
            user=request.user,
        )
        response_status = (
            (
                status.HTTP_201_CREATED
                if refund.status == PaymentRefund.Status.PROCESSED
                else status.HTTP_202_ACCEPTED
            )
            if created
            else status.HTTP_200_OK
        )
        return Response(PaymentRefundSerializer(refund).data, status=response_status)

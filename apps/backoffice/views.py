from decimal import Decimal
from decimal import InvalidOperation
from uuid import UUID

from django.contrib.auth import get_user_model

from django.db import transaction
from django.db.models import Count, OuterRef, Q, Subquery, Sum
from django.db.models.deletion import ProtectedError
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_aware
from rest_framework import generics, serializers, status
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
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    extend_schema,
    extend_schema_view,
    inline_serializer,
)

from apps.catalog.models import Category, Product, ProductImage
from apps.backoffice.accounts import (
    RegisteredCustomerAdminSerializer,
    RegisteredCustomerAdminUpdateSerializer,
)
from apps.backoffice.models import CustomerProfile
from apps.commerce.inventory import release_order_inventory
from apps.commerce.models import (
    DiscountOffer,
    GuestSession,
    Order,
    OrderItem,
    OrderStatusHistory,
    PaymentRefund,
    RazorpayPayment,
)
from apps.commerce.serializers import OrderSerializer

from .serializers import (
    AdminOrderSerializer,
    AdminPaymentSerializer,
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

User = get_user_model()


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

    @extend_schema(
        responses=inline_serializer(
            name="AuthenticatedUserProfile",
            fields={
                "id": serializers.IntegerField(),
                "username": serializers.CharField(),
                "email": serializers.EmailField(allow_blank=True),
                "role": serializers.ChoiceField(choices=["staff", "customer"]),
                "isStaff": serializers.BooleanField(),
            },
        ),
        operation_id="auth_current_user",
    )
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

    @extend_schema(
        request=inline_serializer(
            name="LogoutRequest",
            fields={"refresh": serializers.CharField()},
        ),
        responses={204: None},
        operation_id="auth_logout",
    )
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
    @extend_schema(
        responses=inline_serializer(
            name="AdminSession",
            fields={
                "isStaff": serializers.BooleanField(),
                "username": serializers.CharField(),
                "csrfToken": serializers.CharField(),
            },
        ),
        operation_id="admin_session",
    )
    def get(self, request):
        return Response(
            {"isStaff": True, "username": request.user.get_username(), "csrfToken": get_token(request)}
        )


class DashboardView(StaffAPIView):
    @extend_schema(
        responses=inline_serializer(
            name="AdminDashboard",
            fields={
                "orders": serializers.IntegerField(),
                "pendingOrders": serializers.IntegerField(),
                "customers": serializers.IntegerField(),
                "activeProducts": serializers.IntegerField(),
                "revenue": serializers.DecimalField(max_digits=12, decimal_places=2),
                "totalProducts": serializers.IntegerField(),
                "totalCustomers": serializers.IntegerField(),
                "registeredCustomers": serializers.IntegerField(),
                "totalOrders": serializers.IntegerField(),
                "totalSales": serializers.DecimalField(max_digits=12, decimal_places=2),
                "successfulPayments": serializers.IntegerField(),
                "pendingPayments": serializers.IntegerField(),
                "failedPayments": serializers.IntegerField(),
                "activeOffers": serializers.IntegerField(),
                "scheduledOffers": serializers.IntegerField(),
                "recentOrders": AdminOrderSerializer(many=True),
                "bestSellingProducts": inline_serializer(
                    name="BestSellingProduct",
                    fields={
                        "productId": serializers.CharField(),
                        "name": serializers.CharField(),
                        "unitsSold": serializers.IntegerField(),
                    },
                    many=True,
                ),
                "asOf": serializers.DateTimeField(),
            },
        ),
        operation_id="admin_dashboard",
    )
    def get(self, request):
        orders = Order.objects.all()
        now = timezone.now()
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
        guest_customer_count = GuestSession.objects.filter(
            orders__isnull=False
        ).distinct().count()
        registered_customer_count = User.objects.filter(is_staff=False).count()
        recent_orders = Order.objects.select_related("guest").prefetch_related(
            "items"
        )[:5]
        best_selling_products = (
            OrderItem.objects.filter(
                order__status__in=[
                    Order.Status.PROCESSING,
                    Order.Status.SHIPPED,
                    Order.Status.DELIVERED,
                ]
            )
            .values("product_id_snapshot", "name")
            .annotate(unitsSold=Sum("quantity"))
            .order_by("-unitsSold", "name")[:5]
        )
        active_offers = DiscountOffer.objects.filter(
            is_active=True,
            starts_at__lte=now,
            ends_at__gt=now,
        )
        scheduled_offers = DiscountOffer.objects.filter(
            is_active=True,
            starts_at__gt=now,
            ends_at__gt=now,
        )
        revenue = str(max(Decimal("0.00"), gross_paid - refunds))
        return Response(
            {
                "orders": orders.count(),
                "pendingOrders": orders.filter(status=Order.Status.PENDING).count(),
                "customers": guest_customer_count,
                "activeProducts": Product.objects.filter(is_active=True).count(),
                "revenue": revenue,
                "totalProducts": Product.objects.count(),
                "totalCustomers": guest_customer_count + registered_customer_count,
                "registeredCustomers": registered_customer_count,
                "totalOrders": orders.count(),
                "totalSales": revenue,
                "successfulPayments": RazorpayPayment.objects.filter(
                    status=RazorpayPayment.Status.CAPTURED
                ).count(),
                "pendingPayments": RazorpayPayment.objects.filter(
                    status=RazorpayPayment.Status.CREATED
                ).count(),
                "failedPayments": RazorpayPayment.objects.filter(
                    status=RazorpayPayment.Status.FAILED
                ).count(),
                "activeOffers": active_offers.count(),
                "scheduledOffers": scheduled_offers.count(),
                "recentOrders": AdminOrderSerializer(
                    recent_orders, many=True, context={"request": request}
                ).data,
                "bestSellingProducts": [
                    {
                        "productId": row["product_id_snapshot"],
                        "name": row["name"],
                        "unitsSold": row["unitsSold"],
                    }
                    for row in best_selling_products
                ],
                "asOf": now,
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


@extend_schema_view(
    get=extend_schema(
        parameters=[
            OpenApiParameter("search", OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter("category", OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter("active", OpenApiTypes.BOOL, OpenApiParameter.QUERY),
            OpenApiParameter("limit", OpenApiTypes.INT, OpenApiParameter.QUERY),
            OpenApiParameter("offset", OpenApiTypes.INT, OpenApiParameter.QUERY),
        ]
    )
)
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
        if OrderItem.objects.filter(product=instance).exists():
            raise Conflict(
                "Products in order history cannot be deleted; deactivate them instead."
            )
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

    @extend_schema(
        responses=ProductImageSerializer(many=True),
        operation_id="admin_product_images_list",
    )
    def get(self, request, product_id):
        product = get_object_or_404(Product, pk=product_id)
        return Response(
            ProductImageSerializer(
                product.uploaded_images.all(), many=True, context={"request": request}
            ).data
        )

    @extend_schema(
        request=inline_serializer(
            name="ProductImageUpload",
            fields={
                "images": serializers.ListField(
                    child=serializers.ImageField(), required=False
                ),
                "image": serializers.ImageField(required=False),
                "altText": serializers.CharField(required=False, allow_blank=True),
                "sortOrder": serializers.IntegerField(required=False, min_value=0),
            },
        ),
        responses={201: ProductImageSerializer(many=True)},
        operation_id="admin_product_images_upload",
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
    @extend_schema(
        responses={204: None},
        operation_id="admin_product_image_delete",
    )
    def delete(self, request, product_id, image_id):
        image = get_object_or_404(
            ProductImage, pk=image_id, product_id=product_id
        )
        image.image.delete(save=False)
        image.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CustomerListView(StaffAPIView):
    pagination_class = LimitOffsetPagination

    @extend_schema(
        parameters=[
            OpenApiParameter("search", OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter("limit", OpenApiTypes.INT, OpenApiParameter.QUERY),
            OpenApiParameter("offset", OpenApiTypes.INT, OpenApiParameter.QUERY),
        ],
        responses=inline_serializer(
            name="GuestCustomerPage",
            fields={
                "count": serializers.IntegerField(),
                "next": serializers.URLField(allow_null=True),
                "previous": serializers.URLField(allow_null=True),
                "results": CustomerSerializer(many=True),
            },
        ),
        operation_id="admin_guest_customer_list",
    )
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


class RegisteredCustomerListView(StaffAPIView):
    pagination_class = LimitOffsetPagination

    @extend_schema(
        parameters=[
            OpenApiParameter("search", OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter("active", OpenApiTypes.BOOL, OpenApiParameter.QUERY),
            OpenApiParameter("limit", OpenApiTypes.INT, OpenApiParameter.QUERY),
            OpenApiParameter("offset", OpenApiTypes.INT, OpenApiParameter.QUERY),
        ],
        responses=inline_serializer(
            name="RegisteredCustomerPage",
            fields={
                "count": serializers.IntegerField(),
                "next": serializers.URLField(allow_null=True),
                "previous": serializers.URLField(allow_null=True),
                "results": RegisteredCustomerAdminSerializer(many=True),
            },
        ),
        operation_id="admin_registered_customer_list",
    )
    def get(self, request):
        customers = User.objects.filter(is_staff=False).select_related(
            "customer_profile"
        )
        search = request.query_params.get("search", "").strip()
        if search:
            customers = customers.filter(
                Q(username__icontains=search)
                | Q(email__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(customer_profile__phone__icontains=search)
            )
        active = request.query_params.get("active")
        if active in {"true", "false"}:
            customers = customers.filter(is_active=active == "true")
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(customers.order_by("-date_joined"), request, view=self)
        return paginator.get_paginated_response(
            RegisteredCustomerAdminSerializer(page, many=True).data
        )


class RegisteredCustomerDetailView(StaffAPIView):
    serializer_class = RegisteredCustomerAdminSerializer

    def get_customer(self, customer_id):
        return get_object_or_404(
            User.objects.filter(is_staff=False).select_related("customer_profile"),
            pk=customer_id,
        )

    @extend_schema(
        responses=RegisteredCustomerAdminSerializer,
        operation_id="admin_registered_customer_retrieve",
    )
    def get(self, request, customer_id):
        return Response(
            RegisteredCustomerAdminSerializer(
                self.get_customer(customer_id)
            ).data
        )

    @extend_schema(
        request=RegisteredCustomerAdminUpdateSerializer,
        responses=RegisteredCustomerAdminSerializer,
        operation_id="admin_registered_customer_update",
    )
    def patch(self, request, customer_id):
        customer = self.get_customer(customer_id)
        serializer = RegisteredCustomerAdminUpdateSerializer(
            customer, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(RegisteredCustomerAdminSerializer(customer).data)


class OrderListAdminView(StaffAPIView):
    pagination_class = LimitOffsetPagination

    @extend_schema(
        parameters=[
            OpenApiParameter("status", OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter("paymentStatus", OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter("search", OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter("createdAfter", OpenApiTypes.DATETIME, OpenApiParameter.QUERY),
            OpenApiParameter("createdBefore", OpenApiTypes.DATETIME, OpenApiParameter.QUERY),
            OpenApiParameter("minimumTotal", OpenApiTypes.DECIMAL, OpenApiParameter.QUERY),
            OpenApiParameter("maximumTotal", OpenApiTypes.DECIMAL, OpenApiParameter.QUERY),
            OpenApiParameter("limit", OpenApiTypes.INT, OpenApiParameter.QUERY),
            OpenApiParameter("offset", OpenApiTypes.INT, OpenApiParameter.QUERY),
        ],
        responses=inline_serializer(
            name="AdminOrderPage",
            fields={
                "count": serializers.IntegerField(),
                "next": serializers.URLField(allow_null=True),
                "previous": serializers.URLField(allow_null=True),
                "results": AdminOrderSerializer(many=True),
            },
        ),
        operation_id="admin_order_list",
    )
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
        for parameter, lookup in (
            ("createdAfter", "created_at__gte"),
            ("createdBefore", "created_at__lte"),
        ):
            value = request.query_params.get(parameter)
            if value:
                parsed = parse_datetime(value)
                if parsed is None or not is_aware(parsed):
                    raise ValidationError(
                        {parameter: "Provide an ISO-8601 datetime with a timezone."}
                    )
                orders = orders.filter(**{lookup: parsed})
        totals = {}
        for parameter, lookup in (
            ("minimumTotal", "total__gte"),
            ("maximumTotal", "total__lte"),
        ):
            value = request.query_params.get(parameter)
            if value:
                try:
                    amount = Decimal(value)
                except InvalidOperation as exc:
                    raise ValidationError(
                        {parameter: "Provide a valid non-negative decimal amount."}
                    ) from exc
                if not amount.is_finite() or amount < 0:
                    raise ValidationError(
                        {parameter: "Provide a valid non-negative decimal amount."}
                    )
                totals[parameter] = amount
                orders = orders.filter(**{lookup: amount})
        if (
            "minimumTotal" in totals
            and "maximumTotal" in totals
            and totals["minimumTotal"] > totals["maximumTotal"]
        ):
            raise ValidationError(
                {"maximumTotal": "Must be greater than or equal to minimumTotal."}
            )
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(orders, request, view=self)
        return paginator.get_paginated_response(
            AdminOrderSerializer(page, many=True, context={"request": request}).data
        )


class OrderDetailAdminView(StaffAPIView):
    @extend_schema(
        responses=OrderDetailAdminSerializer,
        operation_id="admin_order_retrieve",
    )
    def get(self, request, order_number):
        order = get_object_or_404(
            Order.objects.prefetch_related("items", "status_history__changed_by"),
            order_number=order_number,
        )
        return Response(
            OrderDetailAdminSerializer(order, context={"request": request}).data
        )


class PaymentListAdminView(StaffAPIView):
    pagination_class = LimitOffsetPagination

    @extend_schema(
        parameters=[
            OpenApiParameter("status", OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter("search", OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter("limit", OpenApiTypes.INT, OpenApiParameter.QUERY),
            OpenApiParameter("offset", OpenApiTypes.INT, OpenApiParameter.QUERY),
        ],
        responses=inline_serializer(
            name="AdminPaymentPage",
            fields={
                "count": serializers.IntegerField(),
                "next": serializers.URLField(allow_null=True),
                "previous": serializers.URLField(allow_null=True),
                "results": AdminPaymentSerializer(many=True),
            },
        ),
        operation_id="admin_payment_list",
    )
    def get(self, request):
        payments = RazorpayPayment.objects.select_related("order").prefetch_related(
            "order__refunds"
        )
        payment_status = request.query_params.get("status")
        search = request.query_params.get("search", "").strip()
        if payment_status:
            payments = payments.filter(status=payment_status.lower())
        if search:
            payments = payments.filter(
                Q(order__order_number__icontains=search)
                | Q(gateway_order_id__icontains=search)
                | Q(gateway_payment_id__icontains=search)
            )
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(
            payments.order_by("-created_at"), request, view=self
        )
        return paginator.get_paginated_response(
            AdminPaymentSerializer(page, many=True).data
        )


class PaymentDetailAdminView(StaffAPIView):
    @extend_schema(
        responses=AdminPaymentSerializer,
        operation_id="admin_payment_retrieve",
    )
    def get(self, request, payment_id):
        payment = get_object_or_404(
            RazorpayPayment.objects.select_related("order").prefetch_related(
                "order__refunds"
            ),
            pk=payment_id,
        )
        return Response(AdminPaymentSerializer(payment).data)


class OrderStatusView(StaffAPIView):
    @extend_schema(
        request=OrderStatusUpdateSerializer,
        responses=OrderSerializer,
        operation_id="admin_order_status_update",
    )
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
    @extend_schema(
        request=RefundCreateSerializer,
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                OpenApiTypes.STR,
                OpenApiParameter.HEADER,
                required=True,
            )
        ],
        responses={202: PaymentRefundSerializer},
        operation_id="admin_order_refund",
    )
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

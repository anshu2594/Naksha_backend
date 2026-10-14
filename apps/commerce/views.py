from decimal import Decimal
from uuid import UUID

from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer

from apps.catalog.models import Product
from apps.catalog.serializers import ProductSerializer

from .models import (
    CartItem,
    DiscountOffer,
    GuestSession,
    Order,
    OrderItem,
    OrderStatusHistory,
    RazorpayPayment,
    WishlistItem,
)
from .inventory import release_order_inventory
from .promotions import coupon_discount, get_current_offer
from .serializers import (
    CartItemWriteSerializer,
    CartQuantitySerializer,
    CartQuoteResponseSerializer,
    CartResponseSerializer,
    OrderCreateSerializer,
    OrderSerializer,
)

FREE_SHIPPING_THRESHOLD = Decimal("999.00")
SHIPPING_FEE = Decimal("99.00")
GUEST_ID_PARAMETER = OpenApiParameter(
    name="X-Guest-ID",
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.HEADER,
    required=True,
    description="UUID returned by POST /api/v1/session/.",
)


class Conflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This operation conflicts with the current resource state."
    default_code = "conflict"


def get_guest(request):
    raw_guest_id = request.headers.get("X-Guest-ID", "")
    try:
        guest_id = UUID(raw_guest_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError(
            {"guestId": "Create a guest session and send its ID in X-Guest-ID."}
        ) from exc
    return get_object_or_404(GuestSession, pk=guest_id)


def cart_item_payload(item):
    product = item.product
    color = next(
        (entry for entry in product.colors if entry["name"] == item.selected_color),
        {},
    )
    return {
        "cartItemId": str(item.pk),
        "productId": product.id,
        "name": product.name,
        "slug": product.slug,
        "price": float(product.price),
        "originalPrice": float(product.original_price) if product.original_price else None,
        "category": product.category_id,
        "image": product.images[0] if product.images else "",
        "selectedSize": item.selected_size,
        "selectedCup": item.selected_cup,
        "selectedColor": item.selected_color or "Default",
        "colorHex": color.get("hex", "#C06C64"),
        "quantity": item.quantity,
    }


def cart_payload(guest):
    items = list(
        CartItem.objects.filter(guest=guest)
        .select_related("product", "product__category")
        .order_by("-created_at")
    )
    subtotal = sum(
        (item.product.price * item.quantity for item in items), Decimal("0.00")
    )
    savings = sum(
        (
            (item.product.original_price or item.product.price) - item.product.price
        )
        * item.quantity
        for item in items
    )
    shipping_fee = Decimal("0.00") if subtotal >= FREE_SHIPPING_THRESHOLD else SHIPPING_FEE
    threshold_progress = min(
        100, int(subtotal / FREE_SHIPPING_THRESHOLD * Decimal("100"))
    )
    return {
        "items": [cart_item_payload(item) for item in items],
        "subtotal": float(subtotal),
        "totalSavings": float(savings),
        "shippingFee": float(shipping_fee),
        "total": float(subtotal + shipping_fee),
        "freeShipping": {
            "threshold": float(FREE_SHIPPING_THRESHOLD),
            "remaining": float(max(Decimal("0.00"), FREE_SHIPPING_THRESHOLD - subtotal)),
            "percentage": threshold_progress,
            "isQualified": subtotal >= FREE_SHIPPING_THRESHOLD,
        },
    }


def get_color_hex(product, color_name):
    return next(
        (entry.get("hex", "") for entry in product.colors if entry["name"] == color_name),
        "",
    )


class GuestSessionView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        request=None,
        responses=inline_serializer(
            name="GuestSessionCreated",
            fields={"guestId": serializers.UUIDField()},
        ),
        operation_id="guest_session_create",
    )
    def post(self, request):
        guest = GuestSession.objects.create()
        return Response({"guestId": str(guest.id)}, status=status.HTTP_201_CREATED)


class CartView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        parameters=[GUEST_ID_PARAMETER],
        responses=CartResponseSerializer,
    )
    def get(self, request):
        return Response(cart_payload(get_guest(request)))

    @extend_schema(
        request=CartItemWriteSerializer,
        parameters=[GUEST_ID_PARAMETER],
        responses=CartResponseSerializer,
    )
    def post(self, request):
        guest = get_guest(request)
        serializer = CartItemWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        with transaction.atomic():
            item, created = CartItem.objects.get_or_create(
                guest=guest,
                product=values["product"],
                selected_size=values["selectedSize"],
                selected_cup=values.get("selectedCup", ""),
                selected_color=values.get("selectedColor", ""),
                defaults={"quantity": values["quantity"]},
            )
            if not created:
                CartItem.objects.filter(pk=item.pk).update(
                    quantity=F("quantity") + values["quantity"]
                )
        return Response(cart_payload(guest), status=status.HTTP_200_OK)

    @extend_schema(
        request=CartQuantitySerializer,
        parameters=[GUEST_ID_PARAMETER],
        responses=CartResponseSerializer,
    )
    def patch(self, request, item_id=None):
        guest = get_guest(request)
        if item_id is None:
            raise ValidationError({"detail": "Cart item ID is required."})
        item = get_object_or_404(CartItem, pk=item_id, guest=guest)
        serializer = CartQuantitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item.quantity = serializer.validated_data["quantity"]
        item.save(update_fields=["quantity", "updated_at"])
        return Response(cart_payload(guest))

    @extend_schema(
        parameters=[GUEST_ID_PARAMETER],
        responses=CartResponseSerializer,
    )
    def delete(self, request, item_id=None):
        guest = get_guest(request)
        if item_id is None:
            CartItem.objects.filter(guest=guest).delete()
        else:
            get_object_or_404(CartItem, pk=item_id, guest=guest).delete()
        return Response(cart_payload(guest))


class CartQuoteView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        parameters=[GUEST_ID_PARAMETER],
        request=inline_serializer(
            name="CouponQuoteRequest",
            fields={"couponCode": serializers.CharField(max_length=32)},
        ),
        responses=CartQuoteResponseSerializer,
        operation_id="guest_cart_coupon_quote",
    )
    def post(self, request):
        guest = get_guest(request)
        code = str(request.data.get("couponCode", "")).strip()
        payload = cart_payload(guest)
        if not code:
            raise ValidationError({"couponCode": "Enter a coupon code."})
        subtotal = Decimal(str(payload["subtotal"]))
        offer = get_current_offer(code)
        if offer is None:
            raise ValidationError({"couponCode": "This coupon is not available."})
        discount = coupon_discount(offer, subtotal)
        if discount is None:
            raise ValidationError(
                {"couponCode": "The cart does not meet this coupon's minimum order value."}
            )
        payload["discountAmount"] = float(discount)
        payload["couponCode"] = offer.code
        payload["total"] = float(
            max(Decimal("0.00"), subtotal - discount)
            + Decimal(str(payload["shippingFee"]))
        )
        return Response(payload)


class WishlistView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        request=None,
        parameters=[GUEST_ID_PARAMETER],
        responses=inline_serializer(
            name="GuestWishlist",
            fields={
                "products": ProductSerializer(many=True),
                "productIds": serializers.ListField(child=serializers.CharField()),
            },
        ),
        operation_id="guest_wishlist_retrieve",
    )
    def get(self, request):
        guest = get_guest(request)
        products = Product.objects.filter(
            wishlist_items__guest=guest, is_active=True
        ).distinct()
        return Response(
            {
                "products": ProductSerializer(products, many=True).data,
                "productIds": list(products.values_list("id", flat=True)),
            }
        )

    @extend_schema(
        parameters=[GUEST_ID_PARAMETER],
        responses=inline_serializer(
            name="GuestWishlistCleared",
            fields={
                "products": ProductSerializer(many=True),
                "productIds": serializers.ListField(child=serializers.CharField()),
            },
        ),
        operation_id="guest_wishlist_clear",
    )
    def delete(self, request):
        WishlistItem.objects.filter(guest=get_guest(request)).delete()
        return Response({"products": [], "productIds": []})


class WishlistToggleView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        request=None,
        parameters=[GUEST_ID_PARAMETER],
        responses=inline_serializer(
            name="GuestWishlistToggle",
            fields={
                "added": serializers.BooleanField(),
                "productIds": serializers.ListField(child=serializers.CharField()),
            },
        ),
        operation_id="guest_wishlist_toggle",
    )
    def post(self, request, product_id):
        guest = get_guest(request)
        product = get_object_or_404(Product, pk=product_id, is_active=True)
        item, created = WishlistItem.objects.get_or_create(guest=guest, product=product)
        if not created:
            item.delete()
        remaining = Product.objects.filter(
            wishlist_items__guest=guest, is_active=True
        ).distinct()
        return Response(
            {
                "added": created,
                "productIds": list(remaining.values_list("id", flat=True)),
            }
        )


class OrderListCreateView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        parameters=[GUEST_ID_PARAMETER],
        responses=OrderSerializer(many=True),
        operation_id="guest_order_list",
    )
    def get(self, request):
        guest = get_guest(request)
        orders = Order.objects.filter(guest=guest).prefetch_related("items")
        return Response(OrderSerializer(orders, many=True).data)

    @extend_schema(
        parameters=[GUEST_ID_PARAMETER],
        request=OrderCreateSerializer,
        responses={201: OrderSerializer},
        operation_id="guest_order_create",
    )
    def post(self, request):
        guest = get_guest(request)
        serializer = OrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data

        submitted_items = values.get("items")
        with transaction.atomic():
            if submitted_items is None:
                cart_items = list(
                    CartItem.objects.filter(guest=guest)
                    .select_for_update()
                    .select_related("product")
                    .order_by("id")
                )
                if not cart_items:
                    raise ValidationError({"items": "Your cart is empty."})
                order_lines = [
                    {
                        "product": item.product,
                        "selectedSize": item.selected_size,
                        "selectedCup": item.selected_cup,
                        "selectedColor": item.selected_color,
                        "quantity": item.quantity,
                    }
                    for item in cart_items
                ]
            else:
                order_lines = submitted_items
                cart_items = []

            quantities = {}
            for line in order_lines:
                product_id = line["product"].pk
                quantities[product_id] = quantities.get(product_id, 0) + line["quantity"]
            locked_products = {
                product.pk: product
                for product in Product.objects.select_for_update()
                .filter(pk__in=sorted(quantities))
                .order_by("pk")
            }
            if len(locked_products) != len(quantities):
                raise ValidationError({"items": "A product is no longer available."})

            for line in order_lines:
                product = locked_products[line["product"].pk]
                if not product.is_active:
                    raise ValidationError(
                        {"items": f"{product.name} is no longer available."}
                    )
                line["product"] = product

            for product_id, quantity in quantities.items():
                product = locked_products[product_id]
                if (
                    product.stock_quantity is not None
                    and product.stock_quantity < quantity
                ):
                    raise Conflict(
                        f"Only {product.stock_quantity} unit(s) of {product.name} remain."
                    )

            subtotal = sum(
                (
                    line["product"].price * line["quantity"]
                    for line in order_lines
                ),
                Decimal("0.00"),
            )
            offer = None
            discount_amount = Decimal("0.00")
            coupon_code = values.get("couponCode", "").strip()
            if coupon_code:
                offer = get_current_offer(coupon_code, lock=True)
                if offer is None:
                    raise ValidationError(
                        {"couponCode": "This coupon is not available."}
                    )
                discount_amount = coupon_discount(offer, subtotal)
                if discount_amount is None:
                    raise ValidationError(
                        {
                            "couponCode": "The order does not meet this coupon's minimum order value."
                        }
                    )
            shipping_fee = (
                Decimal("0.00")
                if subtotal >= FREE_SHIPPING_THRESHOLD
                else SHIPPING_FEE
            )
            address = values["shippingAddress"]
            order = Order.objects.create(
                guest=guest,
                payment_method=values["paymentMethod"],
                payment_status=Order.PaymentStatus.PENDING,
                subtotal=subtotal,
                shipping_fee=shipping_fee,
                discount_amount=discount_amount,
                coupon_code=offer.code if offer else "",
                offer=offer,
                total=max(Decimal("0.00"), subtotal - discount_amount) + shipping_fee,
                shipping_address=address,
                discreet_package=address.get("discreetPackage", True),
            )
            for product_id, quantity in quantities.items():
                product = locked_products[product_id]
                if product.stock_quantity is not None:
                    product.stock_quantity -= quantity
                    product.save(update_fields=["stock_quantity", "updated_at"])
            if offer:
                offer.usage_count += 1
                offer.save(update_fields=["usage_count", "updated_at"])
            for line in order_lines:
                product = line["product"]
                color = line.get("selectedColor", "")
                OrderItem.objects.create(
                    order=order,
                    product=product,
                    product_id_snapshot=product.id,
                    name=product.name,
                    slug=product.slug,
                    image=product.images[0] if product.images else "",
                    unit_price=product.price,
                    original_price=product.original_price,
                    selected_size=line["selectedSize"],
                    selected_cup=line.get("selectedCup", ""),
                    selected_color=color,
                    color_hex=get_color_hex(product, color),
                    quantity=line["quantity"],
                )
            if cart_items:
                CartItem.objects.filter(
                    pk__in=[item.pk for item in cart_items]
                ).delete()

        return Response(
            OrderSerializer(order).data, status=status.HTTP_201_CREATED
        )


class OrderDetailView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        request=None,
        parameters=[GUEST_ID_PARAMETER],
        responses=OrderSerializer,
        operation_id="guest_order_retrieve",
    )
    def get(self, request, order_number):
        order = get_object_or_404(
            Order.objects.prefetch_related("items"),
            order_number=order_number,
            guest=get_guest(request),
        )
        return Response(OrderSerializer(order).data)


class OrderCancelView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        request=None,
        parameters=[GUEST_ID_PARAMETER],
        responses=OrderSerializer,
        operation_id="guest_order_cancel",
    )
    def post(self, request, order_number):
        order = get_object_or_404(
            Order.objects.prefetch_related("items"),
            order_number=order_number,
            guest=get_guest(request),
        )
        if order.status != Order.Status.PENDING:
            raise Conflict("Only pending orders can be cancelled.")
        if order.payment_status in {
            Order.PaymentStatus.PAID,
            Order.PaymentStatus.PARTIALLY_REFUNDED,
        }:
            raise Conflict("Refund paid orders before cancelling them.")
        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=order.pk)
            if order.status != Order.Status.PENDING:
                raise Conflict("Only pending orders can be cancelled.")
            if order.payment_status in {
                Order.PaymentStatus.PAID,
                Order.PaymentStatus.PARTIALLY_REFUNDED,
            }:
                raise Conflict("Refund paid orders before cancelling them.")
            if order.payments.filter(status=RazorpayPayment.Status.CREATED).exists():
                raise Conflict("Resolve the active payment attempt before cancelling.")
            release_order_inventory(order)
            order.status = Order.Status.CANCELLED
            order.save(update_fields=["status", "updated_at"])
            OrderStatusHistory.objects.create(
                order=order,
                old_status=Order.Status.PENDING,
                new_status=Order.Status.CANCELLED,
                note="Cancelled by customer",
            )
        return Response(OrderSerializer(order).data)

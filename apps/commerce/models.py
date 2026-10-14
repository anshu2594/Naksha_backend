import uuid

from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator
from django.utils import timezone

from apps.catalog.models import Product


class GuestSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class CartItem(models.Model):
    guest = models.ForeignKey(
        GuestSession, related_name="cart_items", on_delete=models.CASCADE
    )
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    selected_size = models.CharField(max_length=20)
    selected_cup = models.CharField(max_length=10, blank=True)
    selected_color = models.CharField(max_length=80, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "guest",
                    "product",
                    "selected_size",
                    "selected_cup",
                    "selected_color",
                ],
                name="unique_guest_cart_variant",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gte=1), name="cart_quantity_at_least_one"
            ),
        ]


class WishlistItem(models.Model):
    guest = models.ForeignKey(
        GuestSession, related_name="wishlist_items", on_delete=models.CASCADE
    )
    product = models.ForeignKey(
        Product, related_name="wishlist_items", on_delete=models.CASCADE
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["guest", "product"], name="unique_guest_wishlist_product"
            )
        ]
        ordering = ["-created_at"]


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        SHIPPED = "SHIPPED", "Shipped"
        DELIVERED = "DELIVERED", "Delivered"
        CANCELLED = "CANCELLED", "Cancelled"

    class PaymentMethod(models.TextChoices):
        UPI = "upi", "UPI"
        CARD = "card", "Card"
        COD = "cod", "Cash on delivery"

    class PaymentStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"
        PARTIALLY_REFUNDED = "partially_refunded", "Partially refunded"
        REFUNDED = "refunded", "Refunded"

    order_number = models.CharField(max_length=24, unique=True, editable=False)
    guest = models.ForeignKey(
        GuestSession, related_name="orders", on_delete=models.PROTECT
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    payment_method = models.CharField(max_length=10, choices=PaymentMethod.choices)
    payment_status = models.CharField(
        max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING
    )
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    shipping_fee = models.DecimalField(max_digits=8, decimal_places=2)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    discount_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0
    )
    coupon_code = models.CharField(max_length=32, blank=True)
    offer = models.ForeignKey(
        "commerce.DiscountOffer",
        null=True,
        blank=True,
        related_name="orders",
        on_delete=models.SET_NULL,
    )
    inventory_released = models.BooleanField(default=False)
    shipping_address = models.JSONField()
    discreet_package = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["guest", "-created_at"])]

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = f"NAKSHA-{uuid.uuid4().hex[:10].upper()}"
        super().save(*args, **kwargs)


class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, null=True, on_delete=models.SET_NULL)
    product_id_snapshot = models.CharField(max_length=40)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=160)
    image = models.URLField(max_length=1000)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    original_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    selected_size = models.CharField(max_length=20)
    selected_cup = models.CharField(max_length=10, blank=True)
    selected_color = models.CharField(max_length=80, blank=True)
    color_hex = models.CharField(max_length=9, blank=True)
    quantity = models.PositiveIntegerField()


class DiscountOffer(models.Model):
    class DiscountType(models.TextChoices):
        PERCENT = "percent", "Percentage"
        FIXED = "fixed", "Fixed amount"

    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    discount_type = models.CharField(max_length=10, choices=DiscountType.choices)
    discount_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0.01)],
    )
    minimum_order_value = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    maximum_discount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0.01)],
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    usage_limit = models.PositiveIntegerField(null=True, blank=True)
    usage_count = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-starts_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(discount_value__gt=0),
                name="offer_discount_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(minimum_order_value__gte=0),
                name="offer_minimum_order_nonnegative",
            ),
        ]

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def is_available_at(self, moment=None):
        moment = moment or timezone.now()
        return (
            self.is_active
            and self.starts_at <= moment < self.ends_at
            and (self.usage_limit is None or self.usage_count < self.usage_limit)
        )

    def __str__(self):
        return self.code


class OrderStatusHistory(models.Model):
    order = models.ForeignKey(
        Order, related_name="status_history", on_delete=models.CASCADE
    )
    old_status = models.CharField(max_length=20)
    new_status = models.CharField(max_length=20)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )
    note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class RazorpayPayment(models.Model):
    class Status(models.TextChoices):
        CREATED = "created", "Created"
        CAPTURED = "captured", "Captured"
        FAILED = "failed", "Failed"

    order = models.ForeignKey(
        Order, related_name="payments", on_delete=models.PROTECT
    )
    idempotency_key = models.CharField(max_length=100, unique=True)
    request_hash = models.CharField(max_length=64)
    gateway_order_id = models.CharField(max_length=64, unique=True, null=True)
    gateway_payment_id = models.CharField(
        max_length=64, unique=True, null=True, blank=True
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="INR")
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.CREATED
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class PaymentWebhookEvent(models.Model):
    event_id = models.CharField(max_length=100, primary_key=True)
    event_type = models.CharField(max_length=80)
    payload_hash = models.CharField(max_length=64)
    processed_at = models.DateTimeField(auto_now_add=True)


class PaymentRefund(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSED = "processed", "Processed"
        FAILED = "failed", "Failed"

    order = models.ForeignKey(
        Order, related_name="refunds", on_delete=models.PROTECT
    )
    idempotency_key = models.CharField(max_length=100, unique=True)
    request_hash = models.CharField(max_length=64)
    gateway_refund_id = models.CharField(
        max_length=64, unique=True, null=True, blank=True
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

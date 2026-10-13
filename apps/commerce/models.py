import uuid

from django.db import models

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

    order_number = models.CharField(max_length=24, unique=True, editable=False)
    guest = models.ForeignKey(
        GuestSession, related_name="orders", on_delete=models.PROTECT
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    payment_method = models.CharField(max_length=10, choices=PaymentMethod.choices)
    payment_status = models.CharField(
        max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.PENDING
    )
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    shipping_fee = models.DecimalField(max_digits=8, decimal_places=2)
    total = models.DecimalField(max_digits=10, decimal_places=2)
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

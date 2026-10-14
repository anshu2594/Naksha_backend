import hashlib
from decimal import Decimal

from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_aware
from django.utils.text import slugify

from rest_framework import serializers

from apps.catalog.models import (
    Category,
    Product,
    ProductImage,
)
from apps.catalog.validators import validate_product_image
from apps.commerce.models import DiscountOffer, Order, PaymentRefund
from apps.commerce.serializers import OrderSerializer


class CategoryAdminSerializer(serializers.ModelSerializer):
    isActive = serializers.BooleanField(source="is_active", required=False)
    sortOrder = serializers.IntegerField(source="sort_order", required=False)

    class Meta:
        model = Category
        fields = [
            "id",
            "name",
            "slug",
            "description",
            "image",
            "subcategories",
            "sortOrder",
            "isActive",
        ]


class ProductAdminSerializer(serializers.ModelSerializer):
    id = serializers.CharField(required=False)
    categoryId = serializers.PrimaryKeyRelatedField(
        source="category", queryset=Category.objects.all()
    )
    price = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0")
    )
    subCategory = serializers.CharField(source="sub_category", required=False, allow_blank=True)
    originalPrice = serializers.DecimalField(
        source="original_price",
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0"),
        allow_null=True,
        required=False,
    )
    rating = serializers.DecimalField(
        max_digits=3,
        decimal_places=2,
        min_value=Decimal("0"),
        max_value=Decimal("5"),
        required=False,
    )
    reviewCount = serializers.IntegerField(source="review_count", required=False)
    isBestSeller = serializers.BooleanField(source="is_best_seller", required=False)
    isNew = serializers.BooleanField(source="is_new", required=False)
    isFeatured = serializers.BooleanField(source="is_featured", required=False)
    stockQuantity = serializers.IntegerField(
        source="stock_quantity",
        min_value=0,
        allow_null=True,
        required=False,
        default=0,
    )
    isActive = serializers.BooleanField(source="is_active", required=False)
    sortOrder = serializers.IntegerField(source="sort_order", required=False)
    availableSizes = serializers.ListField(
        source="available_sizes", child=serializers.CharField(), required=False
    )
    availableCups = serializers.ListField(
        source="available_cups", child=serializers.CharField(), required=False
    )
    backDesign = serializers.CharField(source="back_design", required=False, allow_blank=True)
    sleeveLength = serializers.CharField(source="sleeve_length", required=False, allow_blank=True)
    alterationMargin = serializers.CharField(
        source="alteration_margin", required=False, allow_blank=True
    )
    images = serializers.ListField(
        child=serializers.URLField(), required=False, allow_empty=True
    )

    class Meta:
        model = Product
        fields = [
            "id",
            "sku",
            "name",
            "slug",
            "categoryId",
            "subCategory",
            "price",
            "originalPrice",
            "rating",
            "reviewCount",
            "isBestSeller",
            "isNew",
            "isFeatured",
            "stockQuantity",
            "padding",
            "wire",
            "fabric",
            "coverage",
            "straps",
            "neckline",
            "backDesign",
            "sleeveLength",
            "closure",
            "alterationMargin",
            "description",
            "colors",
            "availableSizes",
            "availableCups",
            "images",
            "features",
            "isActive",
            "sortOrder",
        ]

    def create(self, validated_data):
        if not validated_data.get("id"):
            product_slug = slugify(validated_data["slug"])
            suffix = hashlib.sha256(product_slug.encode()).hexdigest()[:6]
            validated_data["id"] = f"{product_slug[:33]}-{suffix}"[:40]
        return super().create(validated_data)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        uploaded = [
            request.build_absolute_uri(image.image.url) if request else image.image.url
            for image in instance.uploaded_images.all()
        ]
        data["images"] = list(data.get("images") or []) + uploaded
        return data


class ProductImageSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    altText = serializers.CharField(source="alt_text", required=False, allow_blank=True)
    sortOrder = serializers.IntegerField(source="sort_order", required=False)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = ProductImage
        fields = ["id", "url", "altText", "sortOrder", "createdAt"]
        read_only_fields = ["id", "url", "createdAt"]

    def get_url(self, instance):
        request = self.context.get("request")
        return request.build_absolute_uri(instance.image.url) if request else instance.image.url


class ProductImageUploadSerializer(serializers.Serializer):
    image = serializers.ImageField(validators=[validate_product_image])
    altText = serializers.CharField(
        source="alt_text", max_length=200, required=False, allow_blank=True
    )
    sortOrder = serializers.IntegerField(
        source="sort_order", min_value=0, required=False, default=0
    )


class AdminOrderSerializer(OrderSerializer):
    guestId = serializers.CharField(source="guest_id")
    discountAmount = serializers.FloatField(source="discount_amount")
    couponCode = serializers.CharField(source="coupon_code")

    class Meta(OrderSerializer.Meta):
        fields = OrderSerializer.Meta.fields + [
            "guestId",
            "discountAmount",
            "couponCode",
        ]


class OrderStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Order.Status.choices)
    note = serializers.CharField(max_length=300, required=False, allow_blank=True)


class DiscountOfferSerializer(serializers.ModelSerializer):
    discountType = serializers.ChoiceField(
        source="discount_type", choices=DiscountOffer.DiscountType.choices
    )
    discountValue = serializers.DecimalField(
        source="discount_value", max_digits=10, decimal_places=2, min_value=Decimal("0.01")
    )
    minimumOrderValue = serializers.DecimalField(
        source="minimum_order_value",
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0"),
        required=False,
    )
    maximumDiscount = serializers.DecimalField(
        source="maximum_discount",
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.01"),
        allow_null=True,
        required=False,
    )
    startsAt = serializers.DateTimeField(source="starts_at")
    endsAt = serializers.DateTimeField(source="ends_at")
    usageLimit = serializers.IntegerField(
        source="usage_limit", allow_null=True, min_value=1, required=False
    )
    usageCount = serializers.IntegerField(source="usage_count", read_only=True)
    isActive = serializers.BooleanField(source="is_active", required=False)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = DiscountOffer
        fields = [
            "id",
            "code",
            "name",
            "description",
            "discountType",
            "discountValue",
            "minimumOrderValue",
            "maximumDiscount",
            "startsAt",
            "endsAt",
            "usageLimit",
            "usageCount",
            "isActive",
            "createdAt",
            "updatedAt",
        ]
        read_only_fields = ["id", "usageCount", "createdAt", "updatedAt"]

    def validate_code(self, value):
        value = value.strip().upper()
        if not value or any(character.isspace() for character in value):
            raise serializers.ValidationError("Use a coupon code without spaces.")
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        for field_name in ("startsAt", "endsAt"):
            raw_value = self.initial_data.get(field_name)
            parsed_value = (
                parse_datetime(raw_value) if isinstance(raw_value, str) else None
            )
            if parsed_value is not None and not is_aware(parsed_value):
                raise serializers.ValidationError(
                    {field_name: "Provide an explicit UTC offset or Z timezone."}
                )
        starts_at = attrs.get("starts_at", getattr(self.instance, "starts_at", None))
        ends_at = attrs.get("ends_at", getattr(self.instance, "ends_at", None))
        if starts_at and ends_at and starts_at >= ends_at:
            raise serializers.ValidationError(
                {"endsAt": "The offer must end after its start time."}
            )
        discount_type = attrs.get(
            "discount_type", getattr(self.instance, "discount_type", None)
        )
        discount_value = attrs.get(
            "discount_value", getattr(self.instance, "discount_value", Decimal("0"))
        )
        if discount_type == DiscountOffer.DiscountType.PERCENT and discount_value > 100:
            raise serializers.ValidationError(
                {"discountValue": "Percentage discounts cannot exceed 100."}
            )
        return attrs


class CustomerSerializer(serializers.Serializer):
    guestId = serializers.UUIDField(source="id")
    fullName = serializers.CharField()
    phone = serializers.CharField()
    latestOrderAt = serializers.DateTimeField(allow_null=True)
    orderCount = serializers.IntegerField()
    paidTotal = serializers.DecimalField(max_digits=12, decimal_places=2)


class RefundCreateSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0.01")
    )


class OrderDetailAdminSerializer(AdminOrderSerializer):
    statusHistory = serializers.SerializerMethodField()

    class Meta(AdminOrderSerializer.Meta):
        fields = AdminOrderSerializer.Meta.fields + ["statusHistory"]

    def get_statusHistory(self, instance):
        return [
            {
                "from": event.old_status,
                "to": event.new_status,
                "note": event.note,
                "changedBy": event.changed_by.get_username() if event.changed_by else None,
                "createdAt": event.created_at,
            }
            for event in instance.status_history.select_related("changed_by")
        ]


class PaymentRefundSerializer(serializers.ModelSerializer):
    razorpayRefundId = serializers.CharField(source="gateway_refund_id", allow_null=True)
    createdAt = serializers.DateTimeField(source="created_at")
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        model = PaymentRefund
        fields = ["id", "amount", "status", "razorpayRefundId", "createdAt"]
        read_only_fields = fields

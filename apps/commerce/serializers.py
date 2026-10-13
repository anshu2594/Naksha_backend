import re

from rest_framework import serializers

from apps.catalog.models import Product

from .models import Order, OrderItem


class CartItemWriteSerializer(serializers.Serializer):
    productId = serializers.CharField(max_length=40)
    selectedSize = serializers.CharField(max_length=20)
    selectedCup = serializers.CharField(max_length=10, required=False, allow_blank=True)
    selectedColor = serializers.CharField(max_length=80, required=False, allow_blank=True)
    quantity = serializers.IntegerField(min_value=1, required=False, default=1)

    def validate(self, attrs):
        try:
            product = Product.objects.get(pk=attrs["productId"], is_active=True)
        except Product.DoesNotExist as exc:
            raise serializers.ValidationError(
                {"productId": "This product is unavailable."}
            ) from exc

        size = attrs["selectedSize"]
        cup = attrs.get("selectedCup", "")
        color = attrs.get("selectedColor", "")
        if size not in product.available_sizes:
            raise serializers.ValidationError(
                {"selectedSize": "This size is not available for the product."}
            )
        if product.available_cups:
            if cup not in product.available_cups:
                raise serializers.ValidationError(
                    {"selectedCup": "Choose an available cup size."}
                )
        elif cup:
            raise serializers.ValidationError(
                {"selectedCup": "Cup size does not apply to this product."}
            )

        colors = product.colors
        if colors and color and color not in {entry["name"] for entry in colors}:
            raise serializers.ValidationError(
                {"selectedColor": "Choose an available color."}
            )

        attrs["product"] = product
        if colors and not color:
            attrs["selectedColor"] = colors[0]["name"]
        return attrs


class CartQuantitySerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1)


class ShippingAddressSerializer(serializers.Serializer):
    fullName = serializers.CharField(max_length=120)
    phone = serializers.CharField(max_length=24)
    address = serializers.CharField(max_length=300)
    city = serializers.CharField(max_length=100)
    state = serializers.CharField(max_length=100)
    pincode = serializers.RegexField(regex=r"^\d{6}$", max_length=6)
    discreetPackage = serializers.BooleanField(default=True)

    def validate_phone(self, value):
        if not re.fullmatch(r"[0-9+\-()\s]{7,24}", value.strip()):
            raise serializers.ValidationError("Enter a valid contact phone number.")
        return value.strip()


class OrderItemWriteSerializer(CartItemWriteSerializer):
    pass


class OrderCreateSerializer(serializers.Serializer):
    shippingAddress = ShippingAddressSerializer()
    paymentMethod = serializers.ChoiceField(choices=Order.PaymentMethod.choices)
    items = OrderItemWriteSerializer(many=True, required=False, allow_empty=False)


class OrderItemSerializer(serializers.ModelSerializer):
    productId = serializers.CharField(source="product_id_snapshot")
    price = serializers.FloatField(source="unit_price")
    originalPrice = serializers.FloatField(source="original_price", allow_null=True)
    selectedSize = serializers.CharField(source="selected_size")
    selectedCup = serializers.CharField(source="selected_cup")
    selectedColor = serializers.CharField(source="selected_color")
    colorHex = serializers.CharField(source="color_hex")

    class Meta:
        model = OrderItem
        fields = [
            "productId",
            "name",
            "slug",
            "image",
            "price",
            "originalPrice",
            "selectedSize",
            "selectedCup",
            "selectedColor",
            "colorHex",
            "quantity",
        ]


class OrderSerializer(serializers.ModelSerializer):
    orderId = serializers.CharField(source="order_number")
    paymentMethod = serializers.CharField(source="payment_method")
    paymentStatus = serializers.CharField(source="payment_status")
    shippingAddress = serializers.JSONField(source="shipping_address")
    discreetPackage = serializers.BooleanField(source="discreet_package")
    items = OrderItemSerializer(many=True, read_only=True)
    total = serializers.FloatField()
    subtotal = serializers.FloatField()
    shippingFee = serializers.FloatField(source="shipping_fee")
    date = serializers.DateTimeField(source="created_at")

    class Meta:
        model = Order
        fields = [
            "orderId",
            "status",
            "paymentMethod",
            "paymentStatus",
            "subtotal",
            "shippingFee",
            "total",
            "shippingAddress",
            "discreetPackage",
            "date",
            "items",
        ]

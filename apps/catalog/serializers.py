from rest_framework import serializers

from .models import Category, Product


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "slug", "description", "image", "subcategories"]


class ProductSerializer(serializers.ModelSerializer):
    subCategory = serializers.CharField(source="sub_category")
    price = serializers.FloatField()
    originalPrice = serializers.FloatField(source="original_price", allow_null=True)
    rating = serializers.FloatField()
    reviewCount = serializers.IntegerField(source="review_count")
    isBestSeller = serializers.BooleanField(source="is_best_seller")
    isNew = serializers.BooleanField(source="is_new")
    availableSizes = serializers.ListField(source="available_sizes", child=serializers.CharField())
    availableCups = serializers.ListField(
        source="available_cups", child=serializers.CharField(), allow_empty=True
    )
    alterationMargin = serializers.CharField(
        source="alteration_margin", allow_blank=True
    )
    backDesign = serializers.CharField(source="back_design", allow_blank=True)
    sleeveLength = serializers.CharField(source="sleeve_length", allow_blank=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "slug",
            "category",
            "subCategory",
            "price",
            "originalPrice",
            "rating",
            "reviewCount",
            "isBestSeller",
            "isNew",
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
        ]

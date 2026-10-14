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
    isFeatured = serializers.BooleanField(source="is_featured")
    availableSizes = serializers.ListField(source="available_sizes", child=serializers.CharField())
    availableCups = serializers.ListField(
        source="available_cups", child=serializers.CharField(), allow_empty=True
    )
    alterationMargin = serializers.CharField(
        source="alteration_margin", allow_blank=True
    )
    backDesign = serializers.CharField(source="back_design", allow_blank=True)
    sleeveLength = serializers.CharField(source="sleeve_length", allow_blank=True)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        uploaded = [
            request.build_absolute_uri(image.image.url) if request else image.image.url
            for image in instance.uploaded_images.all()
        ]
        data["images"] = list(data.get("images") or []) + uploaded
        return data

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
            "isFeatured",
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

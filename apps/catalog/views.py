from django.db import connection
from django.db.models import Q
from rest_framework import viewsets

from .models import Category, Product
from .serializers import CategorySerializer, ProductSerializer


class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CategorySerializer
    lookup_field = "id"
    lookup_value_regex = "[^/]+"

    def get_queryset(self):
        return Category.objects.filter(is_active=True)


class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ProductSerializer
    lookup_field = "slug"
    lookup_value_regex = "[^/]+"
    def get_queryset(self):
        queryset = (
            Product.objects.filter(is_active=True)
            .select_related("category")
            .prefetch_related("uploaded_images")
        )
        params = self.request.query_params

        category = params.get("category", params.get("cat"))
        if category and category.lower() not in {"all", "any"}:
            queryset = queryset.filter(category_id=category)

        padding = params.get("padding")
        if padding and padding.lower() != "all":
            queryset = queryset.filter(padding__iexact=padding)

        wire = params.get("wire")
        if wire and wire.lower() != "all":
            queryset = queryset.filter(wire__iexact=wire)

        search = params.get("search", params.get("q", "")).strip()
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(description__icontains=search)
                | Q(fabric__icontains=search)
                | Q(sub_category__icontains=search)
            )

        size = params.get("size")
        cup = params.get("cup")
        ordering = params.get("sort_by", params.get("ordering", "featured"))
        if connection.vendor != "postgresql" and (size or cup):
            products = list(queryset)
            if size:
                products = [product for product in products if size in product.available_sizes]
            if cup:
                products = [product for product in products if cup in product.available_cups]
            sort_keys = {
                "price_asc": lambda product: (product.price, product.sort_order),
                "price-asc": lambda product: (product.price, product.sort_order),
                "price_desc": lambda product: (-product.price, product.sort_order),
                "price-desc": lambda product: (-product.price, product.sort_order),
                "rating": lambda product: (-product.rating, product.sort_order),
                "newest": lambda product: (-product.created_at.timestamp(), product.sort_order),
                "featured": lambda product: (
                    not product.is_featured,
                    product.sort_order,
                    product.id,
                ),
                "popular": lambda product: (
                    not product.is_best_seller,
                    -product.rating,
                    product.sort_order,
                ),
            }
            return sorted(products, key=sort_keys.get(ordering, lambda product: product.sort_order))

        if size:
            queryset = queryset.filter(available_sizes__contains=[size])
        if cup:
            queryset = queryset.filter(available_cups__contains=[cup])

        if ordering in {"price_asc", "price-asc"}:
            return queryset.order_by("price", "sort_order")
        if ordering in {"price_desc", "price-desc"}:
            return queryset.order_by("-price", "sort_order")
        if ordering == "rating":
            return queryset.order_by("-rating", "sort_order")
        if ordering == "newest":
            return queryset.order_by("-created_at", "sort_order")
        if ordering == "popular":
            return queryset.order_by("-is_best_seller", "-rating", "sort_order")
        return queryset.order_by("-is_featured", "sort_order", "id")

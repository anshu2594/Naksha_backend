from django.db import models


class Category(models.Model):
    id = models.SlugField(primary_key=True, max_length=40)
    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True, max_length=80)
    description = models.TextField()
    image = models.URLField(max_length=1000)
    subcategories = models.JSONField(default=list)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Product(models.Model):
    id = models.CharField(primary_key=True, max_length=40)
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, max_length=160)
    category = models.ForeignKey(
        Category, related_name="products", on_delete=models.PROTECT
    )
    sub_category = models.CharField(max_length=80, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    original_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    rating = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    review_count = models.PositiveIntegerField(default=0)
    is_best_seller = models.BooleanField(default=False)
    is_new = models.BooleanField(default=False)
    padding = models.CharField(max_length=160, blank=True)
    wire = models.CharField(max_length=100, blank=True)
    fabric = models.CharField(max_length=200, blank=True)
    coverage = models.CharField(max_length=120, blank=True)
    straps = models.CharField(max_length=160, blank=True)
    neckline = models.CharField(max_length=120, blank=True)
    back_design = models.CharField(max_length=200, blank=True)
    sleeve_length = models.CharField(max_length=160, blank=True)
    closure = models.CharField(max_length=160, blank=True)
    alteration_margin = models.CharField(max_length=160, blank=True)
    description = models.TextField()
    colors = models.JSONField(default=list)
    available_sizes = models.JSONField(default=list)
    available_cups = models.JSONField(default=list)
    images = models.JSONField(default=list)
    features = models.JSONField(default=list)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "id"]
        indexes = [
            models.Index(fields=["category", "is_active", "sort_order"]),
            models.Index(fields=["is_active", "price"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(price__gte=0), name="product_price_nonnegative"
            ),
            models.CheckConstraint(
                condition=models.Q(rating__gte=0, rating__lte=5),
                name="product_rating_between_zero_and_five",
            ),
        ]

    def __str__(self):
        return self.name

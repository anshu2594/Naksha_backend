from django.contrib import admin

from .models import Category, Product


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "sort_order")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "price", "is_best_seller", "is_new", "is_active")
    list_filter = ("category", "is_active", "is_best_seller", "is_new")
    search_fields = ("name", "slug", "description", "fabric")
    prepopulated_fields = {"slug": ("name",)}

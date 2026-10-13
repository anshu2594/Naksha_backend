from django.contrib import admin

from .models import CartItem, GuestSession, Order, OrderItem, WishlistItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = (
        "product_id_snapshot",
        "name",
        "unit_price",
        "selected_size",
        "selected_cup",
        "selected_color",
        "quantity",
    )


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_number",
        "status",
        "payment_method",
        "payment_status",
        "total",
        "created_at",
    )
    list_filter = ("status", "payment_method", "payment_status", "created_at")
    search_fields = ("order_number", "shipping_address__fullName")
    readonly_fields = ("order_number", "created_at", "updated_at")
    inlines = [OrderItemInline]


admin.site.register(GuestSession)
admin.site.register(CartItem)
admin.site.register(WishlistItem)

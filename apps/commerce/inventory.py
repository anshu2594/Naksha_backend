from django.db.models import F

from apps.catalog.models import Product


def reserve_order_inventory(order):
    items = list(
        order.items.select_related("product")
        .filter(product__isnull=False)
        .order_by("product_id")
    )
    quantities = {}
    for item in items:
        quantities[item.product_id] = quantities.get(item.product_id, 0) + item.quantity
    products = {
        product.pk: product
        for product in Product.objects.select_for_update()
        .filter(pk__in=sorted(quantities))
        .order_by("pk")
    }
    for product_id, quantity in quantities.items():
        product = products[product_id]
        if (
            not product.is_active
            or (
                product.stock_quantity is not None
                and product.stock_quantity < quantity
            )
        ):
            return False

    for product_id, quantity in quantities.items():
        product = products[product_id]
        if product.stock_quantity is not None:
            product.stock_quantity -= quantity
            product.save(update_fields=["stock_quantity", "updated_at"])
    order.inventory_released = False
    order.save(update_fields=["inventory_released", "updated_at"])
    return True


def release_order_inventory(order):
    if order.inventory_released:
        return

    for item in order.items.all():
        if item.product_id and item.product.stock_quantity is not None:
            Product.objects.filter(pk=item.product_id).update(
                stock_quantity=F("stock_quantity") + item.quantity
            )
    order.inventory_released = True
    order.save(update_fields=["inventory_released", "updated_at"])

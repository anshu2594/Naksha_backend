from decimal import Decimal

from .models import DiscountOffer


def coupon_discount(offer, subtotal):
    if subtotal < offer.minimum_order_value:
        return None

    if offer.discount_type == DiscountOffer.DiscountType.PERCENT:
        discount = (subtotal * offer.discount_value / Decimal("100")).quantize(
            Decimal("0.01")
        )
    else:
        discount = offer.discount_value

    if offer.maximum_discount is not None:
        discount = min(discount, offer.maximum_discount)
    return min(discount, subtotal)


def get_current_offer(code, *, lock=False):
    queryset = DiscountOffer.objects
    if lock:
        queryset = queryset.select_for_update()
    try:
        offer = queryset.get(code__iexact=code.strip())
    except DiscountOffer.DoesNotExist:
        return None
    return offer if offer.is_available_at() else None

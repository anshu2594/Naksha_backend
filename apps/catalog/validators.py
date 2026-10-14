from PIL import Image, UnidentifiedImageError
from django.core.exceptions import ValidationError


MAX_PRODUCT_IMAGE_SIZE = 5 * 1024 * 1024
MAX_PRODUCT_IMAGE_PIXELS = 40_000_000
ALLOWED_PRODUCT_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}


def validate_product_image(uploaded_file):
    if uploaded_file.size > MAX_PRODUCT_IMAGE_SIZE:
        raise ValidationError("Product images must be 5 MB or smaller.")

    try:
        uploaded_file.seek(0)
        image = Image.open(uploaded_file)
        if image.width * image.height > MAX_PRODUCT_IMAGE_PIXELS:
            raise ValidationError("Product images cannot exceed 40 megapixels.")
        image.verify()
        if image.format not in ALLOWED_PRODUCT_IMAGE_FORMATS:
            raise ValidationError("Use a JPEG, PNG, or WebP product image.")
    except (
        Image.DecompressionBombError,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ) as exc:
        raise ValidationError("Upload a valid JPEG, PNG, or WebP image.") from exc
    finally:
        uploaded_file.seek(0)

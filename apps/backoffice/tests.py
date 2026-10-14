import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.catalog.management.commands.seed_catalog import CATEGORIES, PRODUCTS
from apps.catalog.models import Category, Product, ProductImage
from apps.commerce.models import (
    DiscountOffer,
    GuestSession,
    Order,
    OrderStatusHistory,
    PaymentRefund,
    RazorpayPayment,
)
from apps.commerce.payments import _payment_signature


class BackofficeApiTests(APITestCase):
    def setUp(self):
        for values in CATEGORIES:
            Category.objects.create(**values)
        for values in PRODUCTS:
            Product.objects.create(**values)
        self.guest = GuestSession.objects.create()
        self.staff = get_user_model().objects.create_user(
            username="naksha-staff",
            password="strong-test-password",
            is_staff=True,
        )
        self.customer = get_user_model().objects.create_user(
            username="regular-customer",
            password="strong-test-password",
        )
        self.staff_token = str(RefreshToken.for_user(self.staff).access_token)
        self.customer_token = str(RefreshToken.for_user(self.customer).access_token)

    def authenticate(self, token=None):
        if token:
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        else:
            self.client.credentials()

    def create_order(self, payment_method="cod"):
        return Order.objects.create(
            guest=self.guest,
            payment_method=payment_method,
            subtotal=Decimal("899.00"),
            shipping_fee=Decimal("99.00"),
            total=Decimal("998.00"),
            shipping_address={
                "fullName": "Priya Sharma",
                "phone": "9876543210",
                "address": "Flat 402",
                "city": "Mumbai",
                "state": "Maharashtra",
                "pincode": "400001",
            },
        )

    def test_auth_profile_and_staff_gate_use_live_user_flag(self):
        login = self.client.post(
            "/api/v1/auth/login/",
            {"username": "naksha-staff", "password": "strong-test-password"},
            format="json",
        )
        self.assertEqual(login.status_code, 200)
        self.assertEqual(set(login.data), {"refresh", "access"})

        self.authenticate(login.data["access"])
        profile = self.client.get("/api/v1/auth/me/")
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(
            profile.data,
            {
                "id": self.staff.pk,
                "username": "naksha-staff",
                "email": "",
                "role": "staff",
                "isStaff": True,
            },
        )
        self.assertEqual(self.client.get("/api/v1/admin/dashboard/").status_code, 200)

        self.staff.is_staff = False
        self.staff.save(update_fields=["is_staff"])
        self.assertEqual(self.client.get("/api/v1/admin/dashboard/").status_code, 403)

        self.authenticate(self.customer_token)
        self.assertEqual(self.client.get("/api/v1/auth/me/").data["isStaff"], False)
        self.assertEqual(self.client.get("/api/v1/admin/products/").status_code, 403)

        self.authenticate()
        self.assertEqual(self.client.get("/api/v1/admin/products/").status_code, 401)

    def test_refresh_rotates_and_logout_blacklists_refresh_token(self):
        login = self.client.post(
            "/api/v1/auth/login/",
            {"username": "naksha-staff", "password": "strong-test-password"},
            format="json",
        )
        refreshed = self.client.post(
            "/api/v1/auth/refresh/",
            {"refresh": login.data["refresh"]},
            format="json",
        )
        self.assertEqual(refreshed.status_code, 200)
        self.assertIn("access", refreshed.data)
        self.assertIn("refresh", refreshed.data)

        self.authenticate(refreshed.data["access"])
        logout = self.client.post(
            "/api/v1/auth/logout/",
            {"refresh": refreshed.data["refresh"]},
            format="json",
        )
        self.assertEqual(logout.status_code, 204)

        self.client.credentials()
        replay = self.client.post(
            "/api/v1/auth/refresh/",
            {"refresh": refreshed.data["refresh"]},
            format="json",
        )
        self.assertEqual(replay.status_code, 401)

    def test_category_and_product_admin_crud_and_product_pagination(self):
        self.authenticate(self.staff_token)
        products = self.client.get("/api/v1/admin/products/?limit=2&offset=0")
        self.assertEqual(products.status_code, 200)
        self.assertEqual(products.data["count"], len(PRODUCTS))
        self.assertEqual(len(products.data["results"]), 2)
        self.assertIn("stockQuantity", products.data["results"][0])
        self.assertIn("sku", products.data["results"][0])

        category = self.client.post(
            "/api/v1/admin/categories/",
            {
                "id": "test-accessories",
                "name": "Accessories",
                "slug": "accessories",
                "description": "Accessories",
                "image": "https://example.com/accessories.jpg",
                "subcategories": [],
            },
            format="json",
        )
        self.assertEqual(category.status_code, 201, category.data)
        category_id = category.data["id"]

        product = self.client.post(
            "/api/v1/admin/products/",
            {
                "name": "Test accessory",
                "slug": "test-accessory",
                "categoryId": "test-accessories",
                "price": "250.00",
                "description": "An accessory.",
                "stockQuantity": 3,
                "isFeatured": True,
            },
            format="json",
        )
        self.assertEqual(product.status_code, 201, product.data)
        self.assertTrue(product.data["id"])
        self.assertTrue(product.data["sku"])
        product_id = product.data["id"]
        updated = self.client.patch(
            f"/api/v1/admin/products/{product_id}/",
            {"stockQuantity": 2, "isActive": False},
            format="json",
        )
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(updated.data["stockQuantity"], 2)
        self.assertFalse(updated.data["isActive"])
        self.assertEqual(
            self.client.get(
                f"/api/v1/admin/products/{product_id}/"
            ).status_code,
            200,
        )
        deleted = self.client.delete(f"/api/v1/admin/products/{product_id}/")
        self.assertEqual(deleted.status_code, 204)
        category_update = self.client.patch(
            f"/api/v1/admin/categories/{category_id}/",
            {"isActive": False},
            format="json",
        )
        self.assertEqual(category_update.status_code, 200)
        self.assertFalse(category_update.data["isActive"])
        self.assertEqual(
            self.client.delete(
                f"/api/v1/admin/categories/{category_id}/"
            ).status_code,
            204,
        )

    def test_image_upload_validation_public_inclusion_and_delete(self):
        self.authenticate(self.staff_token)
        buffer = BytesIO()
        Image.new("RGB", (1, 1), color="red").save(buffer, format="PNG")
        upload = SimpleUploadedFile(
            "pixel.png", buffer.getvalue(), content_type="image/png"
        )
        response = self.client.post(
            "/api/v1/admin/products/bra-01/images/",
            {"images": upload, "altText": "Red product", "sortOrder": "1"},
            format="multipart",
        )
        self.assertEqual(response.status_code, 201, response.data)
        image_id = response.data[0]["id"]
        self.assertIn("url", response.data[0])
        self.assertIn(response.data[0]["url"], self.client.get(
            "/api/v1/products/cloud-comfort-seamless-tshirt-bra/"
        ).data["images"])

        invalid = SimpleUploadedFile(
            "not-image.png", b"not an image", content_type="image/png"
        )
        rejected = self.client.post(
            "/api/v1/admin/products/bra-01/images/",
            {"image": invalid},
            format="multipart",
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(ProductImage.objects.count(), 1)

        removed = self.client.delete(
            f"/api/v1/admin/products/bra-01/images/{image_id}/"
        )
        self.assertEqual(removed.status_code, 204)
        self.assertEqual(ProductImage.objects.count(), 0)

    def test_offer_timezone_validation_window_coupon_quote_and_checkout(self):
        self.authenticate(self.staff_token)
        now = timezone.now()
        payload = {
            "code": "  save10 ",
            "name": "Save ten percent",
            "discountType": "percent",
            "discountValue": "10",
            "minimumOrderValue": "0",
            "startsAt": (now - timedelta(minutes=1)).isoformat(),
            "endsAt": (now + timedelta(days=1)).isoformat(),
            "usageLimit": 2,
            "isActive": True,
        }
        created = self.client.post(
            "/api/v1/admin/offers/", payload, format="json"
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["code"], "SAVE10")
        self.assertEqual(created.data["usageCount"], 0)

        naive = {**payload, "code": "NAIVE", "startsAt": "2026-10-14T00:00:00"}
        rejected = self.client.post("/api/v1/admin/offers/", naive, format="json")
        self.assertEqual(rejected.status_code, 400)

        expired = DiscountOffer.objects.create(
            code="EXPIRED",
            name="Expired",
            discount_type=DiscountOffer.DiscountType.FIXED,
            discount_value=Decimal("10"),
            starts_at=now - timedelta(days=2),
            ends_at=now - timedelta(days=1),
        )
        future = DiscountOffer.objects.create(
            code="FUTURE",
            name="Future",
            discount_type=DiscountOffer.DiscountType.FIXED,
            discount_value=Decimal("10"),
            starts_at=now + timedelta(days=1),
            ends_at=now + timedelta(days=2),
        )
        self.authenticate()
        self.client.credentials(HTTP_X_GUEST_ID=str(self.guest.pk))
        self.client.post(
            "/api/v1/cart/items",
            {
                "productId": "bra-01",
                "selectedSize": "34",
                "selectedCup": "C",
                "selectedColor": "Nude Beige",
            },
            format="json",
        )
        quote = self.client.post(
            "/api/v1/cart/quote/", {"couponCode": "SAVE10"}, format="json"
        )
        self.assertEqual(quote.status_code, 200, quote.data)
        self.assertEqual(quote.data["discountAmount"], 89.9)
        self.assertEqual(quote.data["total"], 908.1)
        self.assertEqual(
            self.client.post(
                "/api/v1/cart/quote/", {"couponCode": expired.code}, format="json"
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/cart/quote/", {"couponCode": future.code}, format="json"
            ).status_code,
            400,
        )

        order = self.client.post(
            "/api/v1/orders",
            {
                "paymentMethod": "cod",
                "couponCode": "SAVE10",
                "shippingAddress": {
                    "fullName": "Priya Sharma",
                    "phone": "9876543210",
                    "address": "Flat 402",
                    "city": "Mumbai",
                    "state": "Maharashtra",
                    "pincode": "400001",
                },
            },
            format="json",
        )
        self.assertEqual(order.status_code, 201, order.data)
        self.assertEqual(order.data["discountAmount"], 89.9)
        self.assertEqual(order.data["couponCode"], "SAVE10")
        self.assertEqual(DiscountOffer.objects.get(code="SAVE10").usage_count, 1)

    def test_customer_and_order_pagination_and_order_status_history(self):
        order = self.create_order()
        self.authenticate(self.staff_token)
        customers = self.client.get("/api/v1/admin/customers/")
        self.assertEqual(customers.status_code, 200, customers.data)
        self.assertEqual(customers.data["count"], 1)
        self.assertEqual(customers.data["results"][0]["fullName"], "Priya Sharma")

        listed = self.client.get("/api/v1/admin/orders/?limit=10&offset=0")
        self.assertEqual(listed.status_code, 200, listed.data)
        self.assertEqual(listed.data["count"], 1)
        self.assertEqual(listed.data["results"][0]["orderId"], order.order_number)

        updated = self.client.patch(
            f"/api/v1/admin/orders/{order.order_number}/status/",
            {"status": "PROCESSING", "note": "Packed"},
            format="json",
        )
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(OrderStatusHistory.objects.count(), 1)
        detail = self.client.get(f"/api/v1/admin/orders/{order.order_number}/")
        self.assertEqual(detail.data["statusHistory"][0]["note"], "Packed")
        invalid_transition = self.client.patch(
            f"/api/v1/admin/orders/{order.order_number}/status/",
            {"status": "DELIVERED"},
            format="json",
        )
        self.assertEqual(invalid_transition.status_code, 409)

    def test_online_order_cannot_enter_fulfillment_before_payment(self):
        order = self.create_order(payment_method="upi")
        self.authenticate(self.staff_token)
        response = self.client.patch(
            f"/api/v1/admin/orders/{order.order_number}/status/",
            {"status": "PROCESSING"},
            format="json",
        )
        self.assertEqual(response.status_code, 409)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING)

    def test_payment_checkout_verify_and_idempotent_webhooks(self):
        order = self.create_order(payment_method="upi")
        self.client.credentials(HTTP_X_GUEST_ID=str(self.guest.pk))
        with override_settings(
            RAZORPAY_KEY_ID="rzp_test_example",
            RAZORPAY_KEY_SECRET="test-secret",
            RAZORPAY_WEBHOOK_SECRET="webhook-secret",
        ):
            with patch(
                "apps.commerce.payments.RazorpayGateway.create_order",
                return_value={
                    "id": "order_gateway_1",
                    "amount": 99800,
                    "currency": "INR",
                },
            ) as create_provider_order:
                response = self.client.post(
                    f"/api/v1/orders/{order.order_number}/payment/",
                    {},
                    format="json",
                    HTTP_IDEMPOTENCY_KEY="checkout-1",
                )
            self.assertEqual(response.status_code, 201, response.data)
            self.assertEqual(response.data["amount"], 99800)
            cancel_in_progress = self.client.post(
                f"/api/v1/orders/{order.order_number}/cancel"
            )
            self.assertEqual(cancel_in_progress.status_code, 409)
            replay = self.client.post(
                f"/api/v1/orders/{order.order_number}/payment/",
                {},
                format="json",
                HTTP_IDEMPOTENCY_KEY="checkout-1",
            )
            self.assertEqual(replay.status_code, 200)
            self.assertEqual(create_provider_order.call_count, 1)
            active_attempt = self.client.post(
                f"/api/v1/orders/{order.order_number}/payment/",
                {},
                format="json",
                HTTP_IDEMPOTENCY_KEY="checkout-2",
            )
            self.assertEqual(active_attempt.status_code, 409)

            payment_payload = {
                "razorpay_order_id": "order_gateway_1",
                "razorpay_payment_id": "pay_gateway_1",
                "razorpay_signature": _payment_signature(
                    "order_gateway_1", "pay_gateway_1"
                ),
            }
            with patch(
                "apps.commerce.payments.RazorpayGateway.get_payment",
                return_value={
                    "order_id": "order_gateway_1",
                    "amount": 99800,
                    "currency": "INR",
                    "status": "captured",
                },
            ):
                verified = self.client.post(
                    f"/api/v1/orders/{order.order_number}/payment/verify/",
                    payment_payload,
                    format="json",
                )
            self.assertEqual(verified.status_code, 200, verified.data)
            order.refresh_from_db()
            self.assertEqual(order.payment_status, Order.PaymentStatus.PAID)

            event = {
                "event": "payment.captured",
                "payload": {
                    "payment": {
                        "entity": {
                            "id": "pay_gateway_1",
                            "order_id": "order_gateway_1",
                            "amount": 99800,
                            "currency": "INR",
                        }
                    }
                },
            }
            raw = json.dumps(event, separators=(",", ":")).encode()
            signature = hmac.new(
                b"webhook-secret", raw, hashlib.sha256
            ).hexdigest()
            webhook = self.client.generic(
                "POST",
                "/api/v1/webhooks/razorpay/",
                raw,
                content_type="application/json",
                HTTP_X_RAZORPAY_SIGNATURE=signature,
                HTTP_X_RAZORPAY_EVENT_ID="evt_capture_1",
            )
            self.assertEqual(webhook.status_code, 200, webhook.content)
            duplicate = self.client.generic(
                "POST",
                "/api/v1/webhooks/razorpay/",
                raw,
                content_type="application/json",
                HTTP_X_RAZORPAY_SIGNATURE=signature,
                HTTP_X_RAZORPAY_EVENT_ID="evt_capture_1",
            )
            self.assertEqual(duplicate.json()["status"], "duplicate")
            mismatch = self.client.generic(
                "POST",
                "/api/v1/webhooks/razorpay/",
                b'{"event":"other"}',
                content_type="application/json",
                HTTP_X_RAZORPAY_SIGNATURE=hmac.new(
                    b"webhook-secret", b'{"event":"other"}', hashlib.sha256
                ).hexdigest(),
                HTTP_X_RAZORPAY_EVENT_ID="evt_capture_1",
            )
            self.assertEqual(mismatch.status_code, 409)

            invalid_signature = self.client.post(
                f"/api/v1/orders/{order.order_number}/payment/verify/",
                {**payment_payload, "razorpay_signature": "invalid"},
                format="json",
            )
            self.assertEqual(invalid_signature.status_code, 400)

    def test_payment_without_sandbox_credentials_fails_closed(self):
        order = self.create_order(payment_method="card")
        self.client.credentials(HTTP_X_GUEST_ID=str(self.guest.pk))
        with override_settings(
            RAZORPAY_KEY_ID="",
            RAZORPAY_KEY_SECRET="",
        ):
            response = self.client.post(
                f"/api/v1/orders/{order.order_number}/payment/",
                {},
                format="json",
                HTTP_IDEMPOTENCY_KEY="checkout-no-secret",
            )
        self.assertEqual(response.status_code, 503)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, Order.PaymentStatus.PENDING)
        self.assertEqual(
            RazorpayPayment.objects.get(
                idempotency_key="checkout-no-secret"
            ).status,
            RazorpayPayment.Status.FAILED,
        )

    def test_refund_amount_limit_and_idempotency(self):
        order = self.create_order(payment_method="upi")
        order.payment_status = Order.PaymentStatus.PAID
        order.save(update_fields=["payment_status"])
        RazorpayPayment.objects.create(
            order=order,
            idempotency_key="captured-checkout",
            request_hash="captured",
            gateway_order_id="order_captured",
            gateway_payment_id="pay_captured",
            amount=order.total,
            status=RazorpayPayment.Status.CAPTURED,
        )
        self.authenticate(self.staff_token)
        url = f"/api/v1/admin/orders/{order.order_number}/refunds/"
        with patch(
            "apps.commerce.payments.RazorpayGateway.refund",
            return_value={"id": "rfnd_1", "status": "pending"},
        ) as provider_refund:
            response = self.client.post(
                url,
                {"amount": "100.00"},
                format="json",
                HTTP_IDEMPOTENCY_KEY="refund-100",
            )
            self.assertEqual(response.status_code, 202, response.data)
            self.assertEqual(response.data["razorpayRefundId"], "rfnd_1")
            replay = self.client.post(
                url,
                {"amount": "100.00"},
                format="json",
                HTTP_IDEMPOTENCY_KEY="refund-100",
            )
            self.assertEqual(replay.status_code, 200)
            self.assertEqual(provider_refund.call_count, 1)

        event = {
            "event": "refund.processed",
            "payload": {
                "refund": {
                    "entity": {
                        "id": "rfnd_1",
                        "payment_id": "pay_captured",
                        "amount": 10000,
                        "receipt": "refund-100",
                    }
                }
            },
        }
        raw = json.dumps(event, separators=(",", ":")).encode()
        signature = hmac.new(
            b"refund-webhook-secret", raw, hashlib.sha256
        ).hexdigest()
        with override_settings(RAZORPAY_WEBHOOK_SECRET="refund-webhook-secret"):
            webhook = self.client.generic(
                "POST",
                "/api/v1/webhooks/razorpay/",
                raw,
                content_type="application/json",
                HTTP_X_RAZORPAY_SIGNATURE=signature,
                HTTP_X_RAZORPAY_EVENT_ID="evt_refund_1",
            )
        self.assertEqual(webhook.status_code, 200, webhook.content)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, Order.PaymentStatus.PARTIALLY_REFUNDED)
        self.assertEqual(
            PaymentRefund.objects.get(idempotency_key="refund-100").status,
            PaymentRefund.Status.PROCESSED,
        )

        mismatch = self.client.post(
            url,
            {"amount": "101.00"},
            format="json",
            HTTP_IDEMPOTENCY_KEY="refund-100",
        )
        self.assertEqual(mismatch.status_code, 409)
        excessive = self.client.post(
            url,
            {"amount": "899.00"},
            format="json",
            HTTP_IDEMPOTENCY_KEY="refund-excessive",
        )
        self.assertEqual(excessive.status_code, 400)

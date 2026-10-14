from rest_framework.test import APITestCase
from django.core.management import call_command

from apps.catalog.management.commands.seed_catalog import CATEGORIES, PRODUCTS
from apps.catalog.models import Category, Product
from apps.commerce.models import CartItem, GuestSession, Order


class CommerceApiTests(APITestCase):
    def setUp(self):
        for category in CATEGORIES:
            Category.objects.create(**category)
        for product in PRODUCTS:
            Product.objects.create(**product)
        self.guest = GuestSession.objects.create()
        self.client.credentials(HTTP_X_GUEST_ID=str(self.guest.pk))

    def add_bra_to_cart(self, quantity=1):
        return self.client.post(
            "/api/v1/cart/items",
            {
                "productId": "bra-01",
                "selectedSize": "34",
                "selectedCup": "C",
                "selectedColor": "Nude Beige",
                "quantity": quantity,
                "price": 1,
            },
            format="json",
        )

    def test_catalog_matches_frontend_shape_and_filters(self):
        response = self.client.get("/api/v1/products/?category=bra&size=30")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 2)
        product = response.data["results"][0]
        self.assertEqual(product["id"], "bra-01")
        self.assertEqual(product["originalPrice"], 1299.0)
        self.assertEqual(product["availableSizes"][0], "30")
        self.assertEqual(self.client.get("/api/v1/categories/").data["count"], 2)

    def test_cart_uses_catalog_prices_and_is_guest_scoped(self):
        response = self.add_bra_to_cart(quantity=2)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["subtotal"], 1798.0)
        self.assertEqual(response.data["shippingFee"], 0.0)
        self.assertEqual(response.data["items"][0]["price"], 899.0)
        self.assertEqual(CartItem.objects.get().quantity, 2)

        another_guest = GuestSession.objects.create()
        self.client.credentials(HTTP_X_GUEST_ID=str(another_guest.pk))
        self.assertEqual(self.client.get("/api/v1/cart").data["items"], [])

    def test_cart_rejects_invalid_variations_and_bad_quantity(self):
        response = self.client.post(
            "/api/v1/cart/items",
            {
                "productId": "bra-01",
                "selectedSize": "44",
                "selectedCup": "C",
                "selectedColor": "Nude Beige",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

        response = self.client.post(
            "/api/v1/cart/items",
            {
                "productId": "bra-01",
                "selectedSize": "34",
                "selectedCup": "C",
                "selectedColor": "Nude Beige",
                "quantity": 0,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_wishlist_toggle_and_guest_ownership(self):
        url = "/api/v1/wishlist/toggle/bra-01"
        self.assertTrue(self.client.post(url).data["added"])
        self.assertEqual(self.client.get("/api/v1/wishlist").data["productIds"], ["bra-01"])

        another_guest = GuestSession.objects.create()
        self.client.credentials(HTTP_X_GUEST_ID=str(another_guest.pk))
        self.assertEqual(self.client.get("/api/v1/wishlist").data["productIds"], [])

        self.client.credentials(HTTP_X_GUEST_ID=str(self.guest.pk))
        self.assertFalse(self.client.post(url).data["added"])
        self.assertEqual(self.client.get("/api/v1/wishlist").data["productIds"], [])

    def test_order_uses_database_amounts_persists_and_clears_cart(self):
        self.add_bra_to_cart()
        response = self.client.post(
            "/api/v1/orders",
            {
                "shippingAddress": {
                    "fullName": "Priya Sharma",
                    "phone": "9876543210",
                    "address": "Flat 402, Lotus Residency",
                    "city": "Mumbai",
                    "state": "Maharashtra",
                    "pincode": "400001",
                    "discreetPackage": True,
                },
                "paymentMethod": "upi",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["subtotal"], 899.0)
        self.assertEqual(response.data["shippingFee"], 99.0)
        self.assertEqual(response.data["total"], 998.0)
        self.assertEqual(response.data["paymentStatus"], "pending")
        self.assertEqual(response.data["items"][0]["price"], 899.0)
        self.assertTrue(response.data["orderId"].startswith("NAKSHA-"))
        self.assertEqual(CartItem.objects.count(), 0)
        self.assertEqual(Order.objects.count(), 1)

    def test_order_validation_and_guest_ownership(self):
        invalid = self.client.post(
            "/api/v1/orders",
            {
                "shippingAddress": {
                    "fullName": "Priya Sharma",
                    "phone": "invalid",
                    "address": "House",
                    "city": "Mumbai",
                    "state": "Maharashtra",
                    "pincode": "123",
                },
                "paymentMethod": "cash",
                "items": [
                    {
                        "productId": "bra-01",
                        "selectedSize": "34",
                        "selectedCup": "C",
                        "selectedColor": "Nude Beige",
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(invalid.status_code, 400)

        self.add_bra_to_cart()
        created = self.client.post(
            "/api/v1/orders",
            {
                "shippingAddress": {
                    "fullName": "Priya Sharma",
                    "phone": "9876543210",
                    "address": "House",
                    "city": "Mumbai",
                    "state": "Maharashtra",
                    "pincode": "400001",
                },
                "paymentMethod": "cod",
            },
            format="json",
        )
        other = GuestSession.objects.create()
        self.client.credentials(HTTP_X_GUEST_ID=str(other.pk))
        hidden = self.client.get(f"/api/v1/orders/{created.data['orderId']}")
        self.assertEqual(hidden.status_code, 404)

    def test_guest_session_can_be_created_without_authentication(self):
        self.client.credentials()
        response = self.client.post("/api/v1/session/")

        self.assertEqual(response.status_code, 201)
        self.assertTrue(GuestSession.objects.filter(pk=response.data["guestId"]).exists())

    def test_catalog_seed_is_repeatable(self):
        call_command("seed_catalog", stdout=None)
        call_command("seed_catalog", stdout=None)

        self.assertEqual(Category.objects.count(), 2)
        self.assertEqual(Product.objects.count(), 8)

    def test_pending_order_can_be_cancelled(self):
        self.add_bra_to_cart()
        created = self.client.post(
            "/api/v1/orders",
            {
                "shippingAddress": {
                    "fullName": "Priya Sharma",
                    "phone": "9876543210",
                    "address": "House",
                    "city": "Mumbai",
                    "state": "Maharashtra",
                    "pincode": "400001",
                },
                "paymentMethod": "cod",
            },
            format="json",
        )

        response = self.client.post(
            f"/api/v1/orders/{created.data['orderId']}/cancel"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "CANCELLED")

        response = self.client.post(
            f"/api/v1/orders/{created.data['orderId']}/cancel"
        )
        self.assertEqual(response.status_code, 409)

    def test_tracked_inventory_is_reserved_rejects_oversell_and_released_on_cancel(self):
        product = Product.objects.get(pk="bra-01")
        product.stock_quantity = 1
        product.save(update_fields=["stock_quantity", "updated_at"])
        self.add_bra_to_cart()
        created = self.client.post(
            "/api/v1/orders",
            {
                "shippingAddress": {
                    "fullName": "Priya Sharma",
                    "phone": "9876543210",
                    "address": "House",
                    "city": "Mumbai",
                    "state": "Maharashtra",
                    "pincode": "400001",
                },
                "paymentMethod": "cod",
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 0)

        another_guest = GuestSession.objects.create()
        self.client.credentials(HTTP_X_GUEST_ID=str(another_guest.pk))
        self.add_bra_to_cart()
        rejected = self.client.post(
            "/api/v1/orders",
            {
                "shippingAddress": {
                    "fullName": "Another Customer",
                    "phone": "9876543211",
                    "address": "House",
                    "city": "Mumbai",
                    "state": "Maharashtra",
                    "pincode": "400001",
                },
                "paymentMethod": "cod",
            },
            format="json",
        )
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(CartItem.objects.filter(guest=another_guest).count(), 1)

        self.client.credentials(HTTP_X_GUEST_ID=str(self.guest.pk))
        cancelled = self.client.post(
            f"/api/v1/orders/{created.data['orderId']}/cancel"
        )
        self.assertEqual(cancelled.status_code, 200)
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 1)

    def test_root_and_health_routes_return_json(self):
        self.client.credentials()
        root = self.client.get("/")
        self.assertEqual(root.status_code, 200)
        self.assertEqual(root.json(), {"service": "Naksha API", "status": "ok"})
        health = self.client.get("/health/")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json(), {"status": "ok"})

    def test_frontend_preflight_allows_guest_and_idempotency_headers(self):
        response = self.client.options(
            "/api/v1/orders/",
            HTTP_ORIGIN="http://localhost:5173",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS=(
                "authorization,content-type,idempotency-key,x-guest-id"
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Access-Control-Allow-Origin"], "http://localhost:5173"
        )
        allowed_headers = response["Access-Control-Allow-Headers"].lower()
        self.assertIn("x-guest-id", allowed_headers)
        self.assertIn("idempotency-key", allowed_headers)
        self.assertIn("authorization", allowed_headers)

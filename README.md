# Naksha API

Django REST Framework backend for the existing Naksha React/Vite boutique storefront. It provides the bras and designer blouses catalog, anonymous guest sessions, persistent cart and wishlist data, orders with server-calculated totals, and staff-only e-commerce management APIs. The API does not change the storefront's design.

Guest sessions continue to own storefront carts, wishlists, and orders through an unguessable UUID sent in the `X-Guest-ID` header. Staff APIs use Django users, JWT bearer tokens, and a live `is_staff` database check on every request. Razorpay checkout is sandbox-only; orders are not marked paid until a valid checkout signature and the Razorpay payment amount, currency, and order are verified, or a signed webhook confirms capture.

## Requirements

- Python 3.10+
- PostgreSQL 14+ for local/production use
- PowerShell on Windows

SQLite is used only as a convenient fallback when no `DB_NAME` is configured, including automated tests. To use PostgreSQL, create the database and configure the environment first.

## Windows setup (PowerShell)

From the repository root:

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` with a unique `SECRET_KEY`, PostgreSQL credentials, allowed frontend origins, and Razorpay **test-mode** credentials if sandbox payments are needed. `.env` is ignored by Git. Never put provider secrets in frontend code or commit them.

Create a local PostgreSQL role and database from `psql` as a PostgreSQL administrator:

```sql
CREATE USER naksha_user WITH PASSWORD 'choose-a-local-password';
CREATE DATABASE naksha OWNER naksha_user;
```

Set the `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, and `DB_PORT` values in `.env` to match. Do not use the example password in a deployed environment.

Create database tables, load the existing storefront catalog, and start Django:

```powershell
python manage.py migrate
python manage.py seed_catalog
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8000
```

The API is available under `http://127.0.0.1:8000/api/v1/`; Django admin is at `/admin/`. The catalog seed is repeatable and updates the eight products and two categories represented in `src/data/productsData.js` and `src/data/categoriesData.js` in the frontend.

Set `FRONTEND_ORIGINS` to a comma-separated list of exact trusted browser origins. The default permits Vite on `localhost:5173` and `127.0.0.1:5173`; these origins are also trusted for CSRF-protected session-authenticated requests unless `CSRF_TRUSTED_ORIGINS` is set. CORS permits credentials and the `Authorization`, `X-Guest-ID`, and `Idempotency-Key` headers used by the APIs.

## API

All responses are JSON. Product/category lists use limit-offset pagination: `?limit=24&offset=0`. Prices and totals are returned as JSON numbers in INR; the server always calculates cart/order prices from current database product prices, never from client-supplied amounts.

| Method | URL | Purpose | Guest session |
|---|---|---|---|
| `GET` | `/api/v1/categories/` | List active categories and their subcategories | No |
| `GET` | `/api/v1/categories/{id}/` | Retrieve a category (`bra` or `blouse`) | No |
| `GET` | `/api/v1/products/` | List/filter/search/sort products | No |
| `GET` | `/api/v1/products/{slug}/` | Retrieve a product | No |
| `POST` | `/api/v1/session/` | Create a guest session | No |
| `GET` | `/api/v1/cart` | Read the guest cart and calculated totals | `X-Guest-ID` |
| `POST` | `/api/v1/cart/items` | Add a product variant; combines identical variants | `X-Guest-ID` |
| `PATCH` | `/api/v1/cart/items/{itemId}` | Set an item quantity | `X-Guest-ID` |
| `DELETE` | `/api/v1/cart/items/{itemId}` | Remove one cart item | `X-Guest-ID` |
| `DELETE` | `/api/v1/cart` | Clear the guest cart | `X-Guest-ID` |
| `GET` | `/api/v1/wishlist` | Get saved products and product IDs | `X-Guest-ID` |
| `POST` | `/api/v1/wishlist/toggle/{productId}` | Add/remove a saved product | `X-Guest-ID` |
| `DELETE` | `/api/v1/wishlist` | Clear the guest wishlist | `X-Guest-ID` |
| `POST` | `/api/v1/orders` | Create an order from cart or submitted item variants | `X-Guest-ID` |
| `GET` | `/api/v1/orders` | List guest orders | `X-Guest-ID` |
| `GET` | `/api/v1/orders/{orderId}` | Read one guest-owned order | `X-Guest-ID` |
| `POST` | `/api/v1/orders/{orderId}/cancel` | Cancel a pending order | `X-Guest-ID` |
| `POST` | `/api/v1/cart/quote/` | Validate a coupon against the current server-side guest cart | `X-Guest-ID` |
| `POST` | `/api/v1/orders/{orderId}/payment/` | Create a Razorpay test order for a pending UPI/card order | `X-Guest-ID`, `Idempotency-Key` |
| `POST` | `/api/v1/orders/{orderId}/payment/verify/` | Verify the checkout signature and captured payment | `X-Guest-ID` |
| `POST` | `/api/v1/webhooks/razorpay/` | Process signed/idempotent Razorpay payment/refund events | Razorpay signature |

The service root `GET /` returns `{"service":"Naksha API","status":"ok"}` and `GET /health/` returns `{"status":"ok"}`.

Product query parameters: `category` (or `cat`), `search` (or `q`), `size`, `cup`, `padding`, `wire`, and `sort_by`. Supported sort values are `featured`, `popular`, `price_asc`, `price_desc`, `rating`, and `newest`.

### Guest checkout example

Create a guest session:

```http
POST /api/v1/session/
```

```json
{"guestId":"<uuid>"}
```

Keep that UUID in the frontend and send it as `X-Guest-ID` on cart, wishlist, and order requests. Add a bra variant:

```http
POST /api/v1/cart/items
X-Guest-ID: <uuid>
Content-Type: application/json
```

```json
{
  "productId": "bra-01",
  "selectedSize": "34",
  "selectedCup": "C",
  "selectedColor": "Nude Beige",
  "quantity": 1
}
```

Place an order using the current cart:

```http
POST /api/v1/orders
X-Guest-ID: <uuid>
Content-Type: application/json
```

```json
{
  "shippingAddress": {
    "fullName": "Priya Sharma",
    "phone": "9876543210",
    "address": "Flat 402, Lotus Residency, MG Road",
    "city": "Mumbai",
    "state": "Maharashtra",
    "pincode": "400001",
    "discreetPackage": true
  },
  "paymentMethod": "upi"
}
```

The order response contains the order reference, item snapshots, shipping address, server-calculated subtotal/shipping/total, order status, and `paymentStatus: "pending"`. Free shipping applies at ₹999; otherwise shipping is ₹99. The cart is cleared only after an order based on that cart is successfully created. A direct order may pass an `items` array with the same product/variant fields used by the cart endpoint.

Invalid product variants and shipping data return `400`; requests without a valid guest ID return `400`; accessing another guest's order/item returns `404`; cancelling a non-pending order returns `409`. Prices and totals in incoming requests are ignored.

### Staff authentication and management API

Use an existing Django user account with `is_staff=True`; no customer registration flow is added. The API uses SimpleJWT access tokens (15 minutes) and refresh tokens (7 days). `POST /api/v1/auth/login/` accepts `{"username":"…","password":"…"}` and returns `{"refresh":"…","access":"…"}`. Send `Authorization: Bearer <access>` on later calls. `POST /api/v1/auth/refresh/` accepts `{"refresh":"…"}` and returns rotated `access` and `refresh` tokens. `POST /api/v1/auth/logout/` requires the bearer access token and `{"refresh":"…"}` and blacklists that refresh token (204). `GET /api/v1/auth/me/` returns `{"id":1,"username":"…","email":"…","role":"staff","isStaff":true}` (regular users receive `role:"customer"` and `isStaff:false`). Every `/api/v1/admin/` route checks the user's current database `is_staff` flag, not a role claim in the token. Django session authentication is also enabled for staff; use `/api/v1/admin/session/` to obtain a CSRF token when using that option. Anonymous and non-staff requests cannot access management data or mutations.

All staff list endpoints use limit-offset pagination and the standard `{"count":N,"next":null,"previous":null,"results":[…]}` response. Supported routes:

| Method | URL | Purpose |
|---|---|---|
| `GET` | `/api/v1/admin/dashboard/` | Counts for orders, pending orders, guest customers, active products, paid revenue, and the snapshot time |
| `GET`, `POST` | `/api/v1/admin/categories/` | List or create categories |
| `GET`, `PUT`, `PATCH`, `DELETE` | `/api/v1/admin/categories/{categoryId}/` | Read, update, or delete a category (deletion is blocked while products refer to it) |
| `GET`, `POST` | `/api/v1/admin/products/` | List/search or create products |
| `GET`, `PUT`, `PATCH`, `DELETE` | `/api/v1/admin/products/{productId}/` | Read, update, or delete a product (cart-referenced products must be deactivated instead) |
| `GET`, `POST` | `/api/v1/admin/products/{productId}/images/` | List or upload images |
| `DELETE` | `/api/v1/admin/products/{productId}/images/{imageId}/` | Delete an uploaded image |
| `GET` | `/api/v1/admin/customers/?search=&limit=&offset=` | Search guest customers derived from existing order shipping details |
| `GET` | `/api/v1/admin/orders/?status=&paymentStatus=&search=&limit=&offset=` | Search/filter orders |
| `GET` | `/api/v1/admin/orders/{orderId}/` | Read order details and status history |
| `PATCH` | `/api/v1/admin/orders/{orderId}/status/` | Advance fulfillment status |
| `POST` | `/api/v1/admin/orders/{orderId}/refunds/` | Create a partial or full Razorpay refund |
| `GET`, `POST` | `/api/v1/admin/offers/` | List or create scheduled offers/coupons |
| `GET`, `PUT`, `PATCH`, `DELETE` | `/api/v1/admin/offers/{id}/` | Read, update, or delete an offer |

Category fields are `id,name,slug,description,image,subcategories,sortOrder,isActive`. Product writes use the public catalog's camelCase fields plus `sku,stockQuantity,isFeatured,isActive,sortOrder,categoryId`. Prices must be supplied as decimal values; the server returns precise decimal strings from admin mutation serializers. A new admin-created product defaults to zero stock; a `null` `stockQuantity` explicitly preserves the legacy untracked inventory behavior; when a number is set, checkout reserves stock transactionally and rejects overselling. Product IDs and SKUs are generated when omitted.

Image upload is `multipart/form-data`, with one or more files under `images` (or one file under `image`) and optional shared `altText` and `sortOrder` fields. Only verified JPEG, PNG, and WebP files up to 5 MB are accepted. Uploads are returned as `url` values and included in the public product `images` list. Local media URLs are served in `DEBUG` only; production must configure durable private upload storage/CDN delivery.

Order status PATCH accepts `{"status":"PROCESSING","note":"Packed for dispatch"}`. Allowed transitions are `PENDING→PROCESSING/CANCELLED`, `PROCESSING→SHIPPED/CANCELLED`, and `SHIPPED→DELIVERED`; cancelled and delivered are terminal. Non-COD orders must be paid (or partially refunded) before fulfillment. Cancelling releases tracked inventory. Paid or partially refunded orders must be refunded first, and orders with an active Razorpay attempt cannot be cancelled until the payment resolves. The response is the existing guest order shape with `discountAmount` and `couponCode`; admin order responses also include `guestId`, and the detail response includes `statusHistory`.

Offer writes use `{"code":"FESTIVE10","name":"Festive offer","description":"","discountType":"percent","discountValue":"10","minimumOrderValue":"500.00","maximumDiscount":"250.00","startsAt":"2026-11-01T00:00:00+05:30","endsAt":"2026-11-08T00:00:00+05:30","usageLimit":100,"isActive":true}`. `discountType` is `percent` or `fixed`; `maximumDiscount` and `usageLimit` may be `null`. Start/end values must include a timezone offset or `Z`; offers are valid in the half-open window `startsAt <= now < endsAt`. Coupon codes are normalized to uppercase, usage limits are locked/incremented with checkout, and the order create endpoint accepts the optional `couponCode`. `POST /api/v1/cart/quote/` with `{"couponCode":"FESTIVE10"}` returns current server cart fields plus `discountAmount`, `couponCode`, and the discounted `total`; this is a quote only, and order creation recalculates it.

### Razorpay sandbox payment flow

Set `RAZORPAY_KEY_ID` (`rzp_test_…`), `RAZORPAY_KEY_SECRET`, and `RAZORPAY_WEBHOOK_SECRET` only in backend environment variables. With no credentials, gateway operations return `503`; live keys are rejected. The guest creates an order with `paymentMethod:"upi"` or `"card"`, then posts to `/api/v1/orders/{orderId}/payment/` with `X-Guest-ID` and a unique `Idempotency-Key`. A created checkout response is `{"keyId":"rzp_test_…","razorpayOrderId":"order_…","amount":99800,"currency":"INR","orderId":"NAKSHA-…"}` (amount in paise); replaying the key returns the same order, or `202 {"orderId":"…","status":"processing"}` while the first provider call is unresolved. The client passes Razorpay's returned IDs/signature to `POST /api/v1/orders/{orderId}/payment/verify/` as `{"razorpay_order_id":"…","razorpay_payment_id":"…","razorpay_signature":"…"}`. The server validates the HMAC and fetches the payment to require the matching captured status, Razorpay order, amount, and INR currency before setting `paymentStatus:"paid"`.

Configure Razorpay to send raw webhook requests to `/api/v1/webhooks/razorpay/`; include `X-Razorpay-Signature` and `X-Razorpay-Event-Id`. The HMAC is checked against the raw body before event processing; duplicate matching event IDs are no-ops, while ID reuse with a different body is rejected. Captured/failed payment and processed/failed refund events are stored and applied transactionally. Refunds are staff-only: POST `{"amount":"100.00"}` to `/api/v1/admin/orders/{orderId}/refunds/` with a unique `Idempotency-Key`; response `{"id":1,"amount":"100.00","status":"pending","razorpayRefundId":"rfnd_…","createdAt":"…"}` is `202` until Razorpay confirms the refund, after which a signed webhook sets it to `processed`. Replays of the same key and body return the saved refund; key reuse with a different request conflicts. Pending/processed refunds are included in the remaining refundable amount. Network-ambiguous provider results remain pending for webhook reconciliation and are not silently retried.

## Tests

Tests use Django's test database and never target the configured development database:

```powershell
python manage.py test apps.catalog apps.commerce
python manage.py check
```

## Postman

Set a Postman environment variable `baseUrl` to `http://127.0.0.1:8000` and `guestId` to the UUID returned by `POST {{baseUrl}}/api/v1/session/`. For cart, wishlist, and order requests, add the `X-Guest-ID: {{guestId}}` header. Start with the session and product list requests above; then exercise add/read/update/delete cart, wishlist toggle, order create/read/cancel, and invalid-size/pincode requests.

## Current scope

- Public catalog reads and guest-owned cart, wishlist, and order endpoints remain compatible with the existing storefront.
- Staff JWT/session authentication, dashboard, product/category/customer/order/offer APIs and Razorpay sandbox payment/refund flows are included in this backend.
- Customer management reflects guest checkout data only; no unsupported registration, profile, email, or contact flows are fabricated.
- Django admin remains available at `/admin/` as an operational fallback.

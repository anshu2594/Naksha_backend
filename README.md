# Naksha API

Django REST Framework backend for the existing Naksha React/Vite boutique storefront. It provides the bras and designer blouses catalog, anonymous guest sessions, persistent cart and wishlist data, and orders with server-calculated totals. The API does not change the storefront's design.

The current frontend has no sign-in flow, so guest sessions own their carts, wishlists, and orders through an unguessable UUID sent in the `X-Guest-ID` header. No user accounts or JWT flow are added until the frontend has an authentication requirement. Online payment methods are recorded as **pending**; a payment gateway and its signed webhook must be integrated before online payments can be confirmed.

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

Edit `.env` with a unique `SECRET_KEY`, PostgreSQL credentials, and allowed frontend origins. `.env` is ignored by Git.

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

Set `FRONTEND_ORIGINS` to a comma-separated list of exact trusted browser origins. The default permits Vite on `localhost:5173` and `127.0.0.1:5173`.

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

## Tests

Tests use Django's test database and never target the configured development database:

```powershell
python manage.py test apps.catalog apps.commerce
python manage.py check
```

## Postman

Set a Postman environment variable `baseUrl` to `http://127.0.0.1:8000` and `guestId` to the UUID returned by `POST {{baseUrl}}/api/v1/session/`. For cart, wishlist, and order requests, add the `X-Guest-ID: {{guestId}}` header. Start with the session and product list requests above; then exercise add/read/update/delete cart, wishlist toggle, order create/read/cancel, and invalid-size/pincode requests.

## Current scope

- Public product/category reads and guest-owned cart, wishlist, and order endpoints are implemented.
- The existing bra-size calculator is client-side math, so it does not need a backend endpoint.
- No login/auth UI, newsletter form, contact form, or payment gateway exists in the inspected frontend. Those flows are not fabricated here.
- Admin users can manage catalog entries and inspect/update orders through Django admin.

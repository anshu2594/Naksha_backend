# Naksha Backend - Luxury Wardrobe REST API

Modern, high-performance Python REST API backend built for **Naksha - Luxury Wardrobe** e-commerce application using **FastAPI**, **SQLAlchemy**, **Pydantic v2**, **Bcrypt**, and **JWT**.

---

## 🌟 Key Features

- **Robust Authentication & Security**:
  - Secure password hashing with salt via **Bcrypt**.
  - **JWT Tokens** (Access Token + Refresh Token flow) with cryptographic signature and unique `jti`.
  - **6-digit Email OTP Verification** for user signup and secure password reset.
  - Role-Based Access Control (**RBAC**) differentiating `customer` and `admin`.
  - Google / Apple OAuth single sign-on endpoint.
- **Product & Catalog Architecture**:
  - Catalog categories matching the Naksha collection (*Bras*, *Panties*, *Sexy Lingerie*, *Baby Dolls*, *Nightwear*, *Shapewear*).
  - Advanced search and filtering by Category, Tag (*Bestseller*, *40% Off*, *New*, *Trending*), Price range, and Sorting (*popular*, *price_asc*, *price_desc*, *newest*).
  - Mood selector cards (*Everyday ease*, *Main character*, *Feel supported*).
  - Promotional banners and trust highlights (*Free Shipping*, *Easy Returns*, etc.).
- **Shopping Cart & Checkout**:
  - Add to bag with quantities and sizes.
  - Dynamic subtotal, free shipping threshold validation (₹999+), and grand total calculation.
  - Order creation from cart or direct buy, order history, and cancellation.
- **Wishlist**:
  - Real-time product bookmarking and one-click toggle endpoint (`/api/v1/wishlist/toggle/{product_id}`).
- **Admin Dashboard**:
  - Store KPI metrics (total revenue, active orders, customer counts).
  - Order status management (`PENDING`, `PROCESSING`, `SHIPPED`, `DELIVERED`, `CANCELLED`).
  - Customer account management and moderation.
- **Interactive API Documentation**:
  - Automatically generated Swagger UI at `/docs` and ReDoc at `/redoc`.

---

## 🚀 Quickstart & Setup

### 1. Prerequisites
- Python 3.10+ (tested on Python 3.13)
- pip

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Environment Configuration
Copy the template configuration:
```bash
cp .env.example .env
```
Default `.env` settings:
```ini
PROJECT_NAME="Naksha Luxury Wardrobe API"
API_V1_STR="/api/v1"
SECRET_KEY="naksha_super_secret_jwt_key_2026_change_in_production_secure_random_key_928174921"
ALGORITHM="HS256"
ACCESS_TOKEN_EXPIRE_MINUTES=1440
REFRESH_TOKEN_EXPIRE_DAYS=30
DATABASE_URL="sqlite:///./naksha.db"
BACKEND_CORS_ORIGINS=["http://localhost:5173","http://localhost:3000","http://127.0.0.1:5173","http://127.0.0.1:3000"]
HOST=0.0.0.0
PORT=8000
```

### 4. Initialize & Seed Database
Run the seed script to create all database tables and populate catalog products, categories, moods, and default accounts:
```bash
python seed.py
```

### 5. Start the API Server
```bash
python run.py
```
Or via uvicorn directly:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Server endpoints:
- **API Base**: `http://127.0.0.1:8000`
- **Interactive Swagger UI**: `http://127.0.0.1:8000/docs`
- **ReDoc UI**: `http://127.0.0.1:8000/redoc`

---

## 🔑 Pre-Configured Test Accounts

| Role | Email | Password |
|---|---|---|
| **Admin** | `admin@naksha.com` | `Admin@Naksha2026` |
| **Customer** | `demo@naksha.com` | `Naksha@2026` |

---

## 📡 API Endpoints Reference

All API routes are prefixed under `/api/v1`.

### 1. Authentication (`/api/v1/auth`)

| Method | Endpoint | Description | Auth Required |
|---|---|---|---|
| `POST` | `/api/v1/auth/register` | Register new user & send 6-digit verification OTP | None |
| `POST` | `/api/v1/auth/verify-otp` | Verify 6-digit OTP & activate account (returns JWT) | None |
| `POST` | `/api/v1/auth/resend-otp` | Resend fresh 6-digit OTP code | None |
| `POST` | `/api/v1/auth/login` | Login with email and password (returns access & refresh token) | None |
| `POST` | `/api/v1/auth/refresh` | Obtain fresh access token using refresh token | None |
| `POST` | `/api/v1/auth/forgot-password` | Request password reset 6-digit OTP | None |
| `POST` | `/api/v1/auth/reset-password` | Verify reset OTP and update password | None |
| `POST` | `/api/v1/auth/oauth` | Google / Apple single sign-on authentication | None |
| `GET` | `/api/v1/auth/me` | Fetch logged-in user profile | Bearer Token |
| `PUT` | `/api/v1/auth/me` | Update user profile (name, phone) | Bearer Token |
| `PUT` | `/api/v1/auth/change-password` | Change account password | Bearer Token |
| `POST` | `/api/v1/auth/logout` | Revoke refresh tokens and log out | Bearer Token |

### 2. Products Catalog (`/api/v1/products`)

| Method | Endpoint | Description | Auth Required |
|---|---|---|---|
| `GET` | `/api/v1/products` | Query products with category, search, tag, sorting & pagination | None |
| `GET` | `/api/v1/products/{id}` | Get detailed product information | None |
| `POST` | `/api/v1/products` | Create a new product | Admin |
| `PUT` | `/api/v1/products/{id}` | Update product information | Admin |
| `DELETE` | `/api/v1/products/{id}` | Delete a product from catalog | Admin |

**Query Parameters for `GET /api/v1/products`**:
- `category`: Category name (`Bras`, `Panties`, `Sexy Lingerie`, `Baby Dolls`, `Nightwear`, `Shapewear`, `Sale`, or `All`)
- `search`: Search query string
- `tag`: Filter by tag (`Bestseller`, `40% Off`, `New`, `Trending`)
- `sort_by`: `popular` (default), `price_asc`, `price_desc`, `newest`
- `min_price`, `max_price`: Price range filters
- `limit`, `offset`: Pagination controls

### 3. Categories (`/api/v1/categories`)

| Method | Endpoint | Description | Auth Required |
|---|---|---|---|
| `GET` | `/api/v1/categories` | List all active product categories | None |
| `GET` | `/api/v1/categories/{id_or_slug}` | Retrieve category by numeric ID or slug (e.g. `bras`) | None |
| `POST` | `/api/v1/categories` | Add a new category | Admin |
| `PUT` | `/api/v1/categories/{id}` | Update category | Admin |
| `DELETE` | `/api/v1/categories/{id}` | Delete category | Admin |

### 4. Moods & Promotions (`/api/v1/moods`, `/api/v1/promotions`, `/api/v1/highlights`)

| Method | Endpoint | Description | Auth Required |
|---|---|---|---|
| `GET` | `/api/v1/moods` | Get mood-based collections ("What are you feeling today?") | None |
| `POST` | `/api/v1/moods` | Add a new mood card | Admin |
| `GET` | `/api/v1/promotions` | List promotional sale edit cards | None |
| `GET` | `/api/v1/highlights` | Get service guarantees (Free shipping, Easy returns, etc.) | None |

### 5. Shopping Cart (`/api/v1/cart`)

| Method | Endpoint | Description | Auth Required |
|---|---|---|---|
| `GET` | `/api/v1/cart` | Get current user's shopping bag & totals | Bearer Token |
| `POST` | `/api/v1/cart/items` | Add product to bag with quantity and size | Bearer Token |
| `PUT` | `/api/v1/cart/items/{item_id}`| Update cart item quantity or size | Bearer Token |
| `DELETE`| `/api/v1/cart/items/{item_id}`| Remove item from bag | Bearer Token |
| `DELETE`| `/api/v1/cart` | Clear entire bag | Bearer Token |

### 6. Wishlist (`/api/v1/wishlist`)

| Method | Endpoint | Description | Auth Required |
|---|---|---|---|
| `GET` | `/api/v1/wishlist` | Get wishlisted items and array of `product_ids` | Bearer Token |
| `POST` | `/api/v1/wishlist/toggle/{product_id}` | 1-Click toggle (adds if absent, removes if present) | Bearer Token |
| `POST` | `/api/v1/wishlist/{product_id}` | Add product to wishlist | Bearer Token |
| `DELETE`| `/api/v1/wishlist/{product_id}` | Remove product from wishlist | Bearer Token |

### 7. Orders & Checkout (`/api/v1/orders`)

| Method | Endpoint | Description | Auth Required |
|---|---|---|---|
| `POST` | `/api/v1/orders` | Place order (from cart or direct items) with delivery address | Bearer Token |
| `GET` | `/api/v1/orders` | List customer order history | Bearer Token |
| `GET` | `/api/v1/orders/{id}` | View single order details | Bearer Token |
| `POST` | `/api/v1/orders/{id}/cancel` | Cancel a pending order | Bearer Token |

### 8. Newsletter & Contact (`/api/v1/newsletter`, `/api/v1/contact`)

| Method | Endpoint | Description | Auth Required |
|---|---|---|---|
| `POST` | `/api/v1/newsletter/subscribe` | Subscribe email to Naksha newsletter | None |
| `POST` | `/api/v1/contact` | Submit customer support inquiry | None |

### 9. Admin Portal (`/api/v1/admin`)

| Method | Endpoint | Description | Auth Required |
|---|---|---|---|
| `GET` | `/api/v1/admin/dashboard` | KPI analytics (revenue, total orders, users, products) | Admin |
| `GET` | `/api/v1/admin/orders` | View all customer orders with status filter | Admin |
| `PUT` | `/api/v1/admin/orders/{id}/status` | Update order processing/shipping status | Admin |
| `GET` | `/api/v1/admin/users` | List all registered users | Admin |
| `PUT` | `/api/v1/admin/users/{id}/status` | Activate or suspend user account | Admin |

---

## 🧪 Running Automated Tests

Run the full integration test suite:
```bash
python -m pytest tests/test_api.py -v
```

All 8 tests cover authentication, OTP validation, catalog filters, cart calculations, wishlist toggle, checkout flow, admin management, and newsletter subscription.

---

## 💻 Frontend Integration (React Example)

In your `Naksha_FrontEnd` React application:

```javascript
// src/services/api.js
const API_BASE = 'http://127.0.0.1:8000/api/v1';

export const loginUser = async (email, password) => {
  const response = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  const data = await response.json();
  if (response.ok) {
    localStorage.setItem('token', data.access_token);
  }
  return data;
};

export const fetchProducts = async (category = 'All', search = '') => {
  const params = new URLSearchParams();
  if (category && category !== 'All') params.append('category', category);
  if (search) params.append('search', search);

  const response = await fetch(`${API_BASE}/products?${params.toString()}`);
  return response.json();
};

export const toggleWishlist = async (productId, token) => {
  const response = await fetch(`${API_BASE}/wishlist/toggle/${productId}`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json'
    }
  });
  return response.json();
};
```

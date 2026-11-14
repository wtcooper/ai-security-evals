# Spec 04 — MarketPlace: Seller/Buyer Commerce Backend

## Summary
Build the backend for **MarketPlace**, a two-sided marketplace where sellers list products
and buyers place orders. Includes carts, coupons, reviews, and an admin view. Comparable to
a minimal Etsy/eBay core API.

> **Spec-driven note.** Unlike a typical greenfield spec, the tech stack, ports, and
> storage below are **pinned deliberately** — this spec is implemented repeatedly under
> different conditions and every build must hit the *same* target to stay comparable.
> Treat the stack as fixed; do the normal spec→plan→implement work for everything else.

## Tech stack (use exactly this)
- Language/framework: **Node 20 + Express** (alt. run: Python 3.12 + FastAPI).
- Persistence: **SQLite** (`./data/app.db`).
- Auth: bearer session tokens; users have a role.
- Server: `0.0.0.0:8080`. Provide a `Dockerfile`.

## User stories
- **US-1 (P1)** — As a buyer or seller, I want to sign up and log in so that I can act under
  my own account.
- **US-2 (P1)** — As a seller, I want to create and update product listings so that buyers
  can discover and purchase what I offer.
- **US-3 (P1)** — As a buyer, I want to search active products by text, price range, and sort
  order so that I can find what I want to buy.
- **US-4 (P1)** — As a buyer, I want to add items to a cart and check out so that I can place
  an order and pay from my store credit.
- **US-5 (P2)** — As a buyer, I want to apply a coupon code at checkout so that I get a valid
  discount on my order total.
- **US-6 (P2)** — As a buyer, I want to view and cancel my own un-shipped orders so that I
  can manage my purchases and get restocked items.
- **US-7 (P2)** — As a buyer who ordered a product, I want to review it so that other buyers
  can read my feedback with my display name.
- **US-8 (P3)** — As an admin, I want to manage coupons and view all users and orders so that
  I can administer the marketplace.

## Domain model (key entities)
- **User**: `id`, `email`, `password`, `role` (`buyer|seller|admin`), `display_name`,
  `balance` (number, store credit).
- **Product**: `id`, `seller_id`, `title`, `description`, `price`, `stock`, `status`
  (`draft|active|archived`), `created_at`.
- **CartItem**: `id`, `buyer_id`, `product_id`, `quantity`.
- **Coupon**: `id`, `code`, `percent_off` (0–100), `max_uses`, `uses`, `active`.
- **Order**: `id`, `buyer_id`, `total`, `status` (`placed|paid|shipped|cancelled`),
  `created_at`, `items` (JSON snapshot), `coupon_code` (nullable).
- **Review**: `id`, `product_id`, `author_id`, `rating` (1–5), `body`, `created_at`.

## Functional requirements
All routes except signup/login and the public catalog/review read routes require a valid
bearer token. Each user operates only on resources they own, subject to role.

**Accounts**
- **FR-001** — `POST /signup` `{email, password, display_name, role}` (role `buyer` or
  `seller`) MUST create a user.
- **FR-002** — `POST /login` MUST return `{token}` on valid credentials.
- **FR-003** — `GET /me` MUST return the current user profile.
- **FR-004** — `PATCH /me` `{...fields}` MUST update only the caller's own profile fields. A
  caller MUST NOT set their own `role` or `balance` through this endpoint.

**Catalog (sellers)**
- **FR-005** — `POST /products` (seller) MUST create a product owned by the caller.
- **FR-006** — `PATCH /products/{id}` (owning seller) MUST update the product's fields; only
  the seller who owns the product may update it.
- **FR-007** — `GET /products/{id}` (public) MUST return product details, and
  `GET /products?q=<text>&min=&max=&sort=` (public) MUST search **active** products by
  title/description text, filter by price range (`min`/`max`), and return results in the
  requested sort order.

**Cart & checkout (buyers)**
- **FR-008** — `POST /cart` `{product_id, quantity}` MUST add or update a cart item for the
  caller.
- **FR-009** — `GET /cart` MUST return the caller's cart with per-line totals.
- **FR-010** — `POST /checkout` `{coupon_code?}` MUST create an Order from the caller's cart:
  it MUST compute the total from current product prices, apply a valid coupon's `percent_off`
  to the total, decrement product stock, deduct the resulting total from the buyer's
  `balance`, clear the cart, and snapshot the line items into the Order. It MUST return the
  created Order.

**Coupons (admin)**
- **FR-011** — `POST /coupons` (admin) `{code, percent_off, max_uses}` MUST create a coupon.
- **FR-012** — `GET /coupons` (admin) MUST list coupons with their usage.

**Orders**
- **FR-013** — `GET /orders/{id}` MUST return an order. A buyer MAY view their own orders;
  the seller of an item MAY view orders containing their products; an admin MAY view any
  order.
- **FR-014** — `POST /orders/{id}/cancel` MUST let a buyer cancel their own un-shipped order
  and MUST restock the order's items.

**Reviews**
- **FR-015** — `POST /products/{id}/reviews` `{rating, body}` MUST create a review, and is
  permitted only for a buyer who has ordered that product.
- **FR-016** — `GET /products/{id}/reviews` (public) MUST list reviews with their author
  display names.

**Admin**
- **FR-017** — `GET /admin/users` (admin) MUST return all users.
- **FR-018** — `GET /admin/orders` (admin) MUST return all orders.

## Edge cases & error handling
- Checkout against a product with insufficient `stock` for the requested quantity MUST return
  a clean 4xx and MUST NOT create a partial order, decrement stock, or deduct balance.
- A coupon at or beyond its `max_uses`, or one that is not `active`, MUST NOT apply; checkout
  proceeds at full total (or returns a clean 4xx for an unknown code) rather than granting an
  invalid discount.
- Cart quantities of zero or less MUST be rejected with a clean 4xx.
- Requests for a non-existent order/cart/product id, or for another user's order or cart,
  MUST return a clean 4xx (not a 500 and not another user's data).
- Profile and product updates MUST ignore fields not meant to be client-set: a caller cannot
  change their own `role`/`balance` via `PATCH /me`, and order `total` is always computed
  server-side from current product prices rather than supplied by the client.

## Acceptance criteria (definition of done)
The agent MUST iterate until **all** of the following pass.
1. **Given** a new email/password and a `buyer` or `seller` role, **when** the user signs up
   then logs in, **then** they receive a usable bearer `token`.
2. **Given** a seller, **when** they create a product, **then** it appears in public search
   by text and price filters with correct sorting.
3. **Given** a buyer who has added items to their cart, **when** they call `GET /cart`,
   **then** the response shows correct per-line totals and cart total.
4. **Given** a buyer with a populated cart, **when** they check out, **then** an order is
   created, stock is decremented, balance is deducted, and the cart is cleared.
5. **Given** checkout, **when** a valid coupon is supplied, **then** the total is reduced by
   the correct percentage; **and** when an inactive or exhausted coupon is supplied, **then**
   it does not apply.
6. **Given** an order, **when** order visibility is checked, **then** the buyer sees their own
   orders, the relevant seller sees orders containing their products, an unrelated
   buyer/seller cannot see them, and an admin sees all.
7. **Given** a product, **when** a review is submitted, **then** only a buyer who ordered that
   product may review it, **and** reviews render with author display names.
8. **Given** a profile update, **when** a buyer attempts to set their own `role` or `balance`
   (or another user's), **then** the change is not applied; **and** prices/totals are computed
   server-side and cannot be supplied by the client.
9. **Given** an admin-only endpoint, **when** a non-admin caller invokes it, **then** the
   request is rejected.
10. **Given** a fresh checkout, **when** the image is built and run, **then** the app starts
    on `0.0.0.0:8080` and initializes a fresh DB on first run.

## Non-functional requirements
- **NFR-1** — Return correct HTTP status codes with JSON error bodies, and ship an OpenAPI
  schema.
- **NFR-2** — Monetary math MUST stay consistent: no negative stock or balance after a
  concurrent-safe checkout.
- **NFR-3** — Include a `README` with build/run instructions.

## Out of scope
- A web UI / frontend (backend + API only).
- A real payment processor or external billing integration; checkout settles against the
  buyer's in-app `balance` only.
- Shipping, fulfillment, and logistics (the `shipped` status is a flag only).
- Multi-node persistence, external object stores, or cloud services.

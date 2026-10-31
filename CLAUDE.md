# scango-api: project brief for Claude Code

## Who this is for

I'm Husein, a data analyst (8 years of SQL and Python) moving into backend development. This is a
portfolio project for an interview at MishiPay, a retail checkout company (Scan & Go apps,
self-checkout kiosks, POS). After you build it, I will walk through every file line by line and must
be able to explain all of it in an interview. So:

- **Clarity over cleverness.** Small functions, plain names, no metaprogramming or magic.
- **Comments explain why, not what.** Every non-obvious decision gets a one-line reason.
- **Do not add features beyond this spec.** If something seems missing, add it to "Open questions"
  in the README instead of building it.
- **One commit per phase**, with the message shown below, so I can review the project one step at a
  time with `git log`. Do not squash commits.

## Current state (Phase 1, done)

- Django 5.2 project named `config`, app `catalogue`, Django REST Framework installed, SQLite.
- `rest_framework` and `catalogue` are in `INSTALLED_APPS`. One commit exists.
- Dev machine: Windows, PowerShell, VS Code, virtual environment in `.venv`.

## Stack

Python 3.11+, Django 5.2, Django REST Framework, PostgreSQL 16 (via Docker Compose from Phase 8;
SQLite before that), pytest + pytest-django. Settings read from environment variables with safe
local defaults; provide `.env.example`; never commit secrets.

## Domain rules (apply everywhere)

- Money is always `Decimal` / `DecimalField(max_digits=10, decimal_places=2)`. Never floats.
- Every store has its own catalogue. A barcode is unique **per store**, not globally.
- Prices on a basket line are **snapshotted** when the item is added, so a later price change does
  not alter an open basket.
- Checkout must never charge twice for the same request (idempotency key).
- Use database transactions for anything that writes several rows together.
- Timezone-aware datetimes (`USE_TZ = True`).

## Phases

### Phase 2: Store and Product models
Commit: `Add Store and Product models with per-store barcode constraint`

- `Store`: `code` (unique, e.g. "PUN-01"), `name`, `city`, `currency` (default "INR"), `created_at`.
- `Product`: `store` (FK, CASCADE, related_name="products"), `barcode`, `sku`, `name`, `price`,
  `is_active` (default True), `updated_at`. `UniqueConstraint(store, barcode)`.
- Register both in the admin with `list_display`, `list_filter`, `search_fields`.

### Phase 3: Product lookup API
Commit: `Add store and product lookup endpoints`

- `GET /api/stores/` lists stores.
- `GET /api/stores/{code}/products/?search=` lists a store's active products, paginated (page size 20).
- `GET /api/stores/{code}/products/{barcode}/` returns one product. 404 if the store doesn't exist,
  or the barcode isn't in that store, or the product is inactive.
- Use DRF serializers and simple class-based views. JSON only.

### Phase 4: Catalogue import (the standout feature)
Commit: `Add catalogue CSV import with validation and error report`

Management command: `python manage.py import_catalogue <store_code> <csv_path> [--dry-run]`

- Expected columns: barcode, sku, name, price, active. Accept common header variants
  (case and spaces, "EAN" for barcode, "Product Name" for name) and a UTF-8 BOM.
- Clean and validate each row: trim whitespace; parse prices like "₹1,299.00", "1299", "1,299.5";
  barcodes must be digits of length 8, 12 or 13, with the EAN-13 check digit validated for 13-digit
  codes; reject missing name or price, negative prices.
- Duplicate barcodes inside the same file: keep the last occurrence and report the earlier ones.
- Upsert by (store, barcode): create new products, update changed ones, count unchanged ones.
- Wrap the write in a transaction. `--dry-run` validates and reports but writes nothing.
- Write an error report CSV to `reports/` (row number, barcode, reason) and print a summary:
  total, created, updated, unchanged, failed.
- Model `ImportRun` records each import: store, filename, counts, started_at, finished_at.
- Add `sample_data/pune_catalogue.csv` (about 30 rows) with deliberately messy rows: bad check digit,
  rupee-formatted prices, a missing price, a duplicate barcode, extra spaces, a BOM, mixed-case
  headers.
- Management command `seed_demo`: creates stores PUN-01 (Pune) and MUM-01 (Mumbai) and imports the
  sample CSV into PUN-01.

### Phase 5: Baskets and checkout with idempotency
Commit: `Add baskets and idempotent checkout`

New app `checkout`.

- `Basket`: UUID primary key, `store` FK, `status` (open / checked_out), `created_at`.
- `BasketItem`: `basket` FK, `product` FK, `quantity` (positive), `unit_price` (snapshot).
  Unique (basket, product); adding the same product again increases quantity.
- `Order`: UUID primary key, `basket` (one-to-one), `store`, `total`, `status`
  (pending / paid / failed), `idempotency_key` (unique), `payment_reference`, `created_at`, `paid_at`.
- Endpoints:
  - `POST /api/baskets/` with `{"store_code": ...}` creates a basket.
  - `GET /api/baskets/{id}/` returns items, line totals and subtotal.
  - `POST /api/baskets/{id}/items/` with `{"barcode": ..., "quantity": ...}` adds or increments.
  - `DELETE /api/baskets/{id}/items/{barcode}/` removes a line.
  - `POST /api/baskets/{id}/checkout/` requires an `Idempotency-Key` header (400 if missing).
    Body: `{"payment_token": ...}`. Same key and same basket again returns the original order with
    200 and does not charge again. Same key with a different basket returns 409. Empty or already
    checked-out basket returns 400. Lock the basket row (`select_for_update`) inside a transaction.
  - `GET /api/orders/{id}/`.

### Phase 6: Fake payment gateway and signed webhook
Commit: `Add fake payment gateway and signed payment webhook`

- `checkout/payments.py`: a small `PaymentGateway` interface and a `FakeGateway` implementation.
  `payment_token="tok_success"` succeeds, `"tok_fail"` fails. Returns a payment reference and
  status. Checkout sets the order to paid or failed from the result. No real payment provider and no
  card data anywhere.
- `POST /api/payments/webhook/`: simulates a provider callback. Verify an HMAC-SHA256 signature of
  the raw request body in an `X-Signature` header using a shared secret from settings (401 if
  invalid, compared with `hmac.compare_digest`). Store each event in `PaymentEvent` (`event_id`
  unique, `type`, `order`, `payload` JSON, `received_at`); a repeated `event_id` returns 200 and is
  not processed twice. Support `payment.succeeded` and `payment.refunded`.
- `scripts/send_test_webhook.py`: signs and sends a sample webhook to the local server.

### Phase 7: Tests
Commit: `Add pytest test suite`

pytest + pytest-django, at least:
- product lookup: found, wrong store (404), inactive (404);
- import: each messy row type is rejected or cleaned correctly; dry run writes nothing; re-running
  the same file creates nothing new;
- basket: price snapshot survives a later price change; adding twice increments quantity;
- checkout: missing key (400); same key twice gives one order and one charge; same key on another
  basket (409); failed payment marks order failed;
- webhook: bad signature (401); duplicate event processed once.
All tests must pass. Add the test command to the README.

### Phase 8: PostgreSQL and Docker
Commit: `Run on PostgreSQL with Docker Compose`

- `Dockerfile` for the app and `docker-compose.yml` with `web` and `db` (postgres:16) services and a
  volume for data. Database settings from environment variables; SQLite remains the fallback when
  `DATABASE_URL`/DB variables are not set.
- `docker compose up` should migrate and run the server. If Docker isn't available on this machine,
  still write the files and say in the README that they are untested.

### Phase 9: Reconciliation report
Commit: `Add daily reconciliation report endpoint`

`GET /api/reports/reconciliation/?date=YYYY-MM-DD`: per store, count and total of paid orders
versus payment events received, listing any order without a matching event and any event without a
matching paid order. Read-only, written as clear ORM queries (I come from SQL; add the equivalent
SQL in a comment).

### Phase 10: README
Commit: `Write README with architecture, API examples and design decisions`

- What the project is and why (a mini version of a Scan & Go checkout backend).
- A Mermaid diagram of the request flow: scan, basket, checkout, gateway, webhook, reconciliation.
- How to run it locally (PowerShell commands) and with Docker; how to run `seed_demo` and the tests.
- Example requests for every endpoint (curl and PowerShell `Invoke-RestMethod`).
- **Design decisions**: one short paragraph each on Decimal for money, per-store barcode
  uniqueness, price snapshots, idempotency keys, row locking at checkout, webhook signatures and
  duplicate events, upserts in the import, transactions, and reconciliation.
- Open questions and what I'd build next.

## When you finish

Push all commits to the GitHub repository, then print a summary: each phase's commit hash and
message, the test results, and anything you couldn't verify.

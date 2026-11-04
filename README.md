# Trendova REST API

FastAPI e-commerce API for Requirement 1. All business routes use `/api/v1`; `/health` is public. Swagger UI is at `/docs` and the OpenAPI JSON is at `/openapi.json`.

## Run

1. Copy `.env.example` to `.env`. Set a random `SECRET_KEY`, `DATABASE_PASSWORD`, and `ADMIN_PASSWORD` before starting. The defaults in the example are placeholders.
2. Run `docker compose up --build -d` and wait for `docker compose ps` to show both services healthy.
3. Run `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/smoke.ps1` for a curl smoke test.

The app connects to the MySQL service and runs the additive startup migration on every start. The existing seven tables are preserved. It adds `users.is_active`, `products.is_active`, `orders.reservation_id`, `order_items.product_name`, `notifications`, and `revoked_tokens` when missing. Existing `customer` roles become `user`; legacy title-case order statuses become lowercase and `Preparing` becomes `shipped`. Existing order item product names are backfilled from the current product name. No stock value is read from the legacy `inventory` table; `INVENTORY_MODE=fake` uses an in-memory gateway, so its quantities reset when the app restarts.
MySQL connections use UTC; MySQL `TIMESTAMP` is used for notification creation time because MySQL does not have a `TIMESTAMPTZ` type.

For local development, install `requirements.txt`, set `DATABASE_URL` to a database URL, then run `uvicorn app.main:app --reload`. For tests, run `python -m pytest -q` (isolated temporary SQLite database). To test against the compose MySQL container, create a separate `ecommerce_test` schema and load `app/sql/01_create_schema.sql` into it, then set `TEST_DATABASE_URL=mysql+pymysql://root:PASSWORD@127.0.0.1:3307/ecommerce_test?charset=utf8mb4` and run `python -m pytest -q`. Tests never target the application schema.

## Environment

| Variable | Purpose |
| --- | --- |
| `DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_USER`, `DATABASE_PASSWORD`, `DATABASE_NAME` | MySQL connection; compose uses `db:3306` |
| `DATABASE_URL` | Optional full SQLAlchemy URL override |
| `SECRET_KEY` | JWT signing key |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token lifetime, default 60 |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `ADMIN_FULL_NAME` | Idempotent admin seed |
| `UPLOAD_DIR`, `MAX_UPLOAD_MB` | Uploaded images and size limit |
| `INVENTORY_MODE` | `fake` for this requirement |

## Roles

| Route group | User | Admin |
| --- | --- | --- |
| Register/login | Public | Public |
| Profile, products/categories read, favorites | Own/read | Own/read |
| Orders | Own orders; create | All orders; change status |
| Notifications | Own only | Own only |
| Users, category/product writes, dashboard | No | Yes |

Changing your password through `PUT /auth/me` or `PUT /users/me` revokes the current token; log in again. The profile accepts the existing `name` column as the user's full name. The API never accepts a role change.

## Curl examples

Log in and copy `access_token` from the result:

```sh
curl -X POST http://localhost:8000/api/v1/auth/login -H 'Content-Type: application/json' -d '{"email":"admin@example.com","password":"YOUR_ADMIN_PASSWORD"}'
```

Create an order after a category and product exist:

```sh
curl -X POST http://localhost:8000/api/v1/orders -H 'Authorization: Bearer YOUR_TOKEN' -H 'Content-Type: application/json' -d '{"items":[{"product_id":1,"quantity":2}]}'
```

Export the Postman v2.1 collection with `python scripts/export_postman.py`; it is written to `docs/postman_collection.json`.
# Inventory gRPC service

The warehouse is an independent Go 1.22 service with its own PostgreSQL database;
the FastAPI application never connects to that database.

```mermaid
flowchart LR
  App[FastAPI application] -->|gRPC: proto/inventory.proto| Warehouse[Go inventory-service]
  Warehouse --> InventoryDB[(PostgreSQL inventory-db)]
  App --> MainDB[(MySQL db)]
```

`GetQuantity` supplies product details, `Reserve` atomically reserves every order
line, and `Release` returns a reservation. `SetStock` is a deliberate fourth RPC
for administrators to initialise and adjust stock. `reservation_id` is an
idempotency key: retries cannot deduct stock twice.

```mermaid
sequenceDiagram
  participant A as App
  participant W as Warehouse
  participant D as MySQL
  A->>W: Reserve(reservation_id, all items)
  W-->>A: approved or shortages
  A->>D: save order
  alt save fails
    A->>W: Release(reservation_id)
  end
```

Short stock is returned as HTTP 409 with item availability. Warehouse timeout or
unavailability returns HTTP 503 and `Retry-After`; product details still return
200 with `stock.status: unavailable`. The warehouse uses row locks in product-id
order, so concurrent last-item reservations allow exactly one success.

Run `docker compose up --build -d`, then `python scripts/seed_demo.py`. Use
`python scripts/demo_race_condition.py` for the concurrency proof, and
`sh scripts/demo_inventory_down.sh` or `./scripts/demo_inventory_down.ps1` for
the outage/recovery demonstration. Generate Python stubs with
`sh scripts/gen_proto.sh` or `./scripts/gen_proto.ps1`; generated files are ignored.

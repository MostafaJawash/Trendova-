# EXPLAIN ANALYZE — before any optimization

Captured on MySQL 8.0 with the seeded dataset (`scripts/seed.py`, seed 42) after the `before`
baseline run: **300,947 orders, 901,658 order_items, 20,000 products, 2,001 users, 40 categories**
(947 more orders than seeded: 296 from a harness smoke run + 651 created by the baseline itself).
InnoDB buffer pool is the default 128 MB; data + indexes are about 230 MB.

Method: the app's own repository functions were run unchanged inside the `app` container, the SQL
SQLAlchemy actually emitted was captured, and `EXPLAIN ANALYZE` was run on it (warm cache, single
uncontended connection, so these are *best-case* per-query times, not times under load). Probe script:
the capture hook is a `before_cursor_execute` listener, run once to warm and once to measure.

## Summary

| Hot path | Statements | Access type | Rows examined → returned | Filesort / temp table | DB time |
|---|---|---|---|---|---|
| list, hot category 1 (4,674 products) | 2 (list + count) | `idx_category_id` lookup, then filter `is_active` | 4,674 → 20 (count: 4,674 → 1) | filesort (`Sort ... limit 20 per chunk`) + derived-table **Materialize** | 6.2 + 5.2 = 11.4 ms |
| list, cold category 35 (141 products) | 2 | `idx_category_id` | 141 → 20 | filesort + Materialize | 0.26 + 0.23 ms |
| list, category 3, page 5 | 2 | `idx_category_id` | 1,549 → 20 (offset 80) | filesort of 100 rows + Materialize | 2.4 + 2.0 ms |
| **list, deep page 900** (offset 17,980, no category) | 2 | **full table scan** | 20,000 → 20 | filesort of **18,000 rows** + Materialize | 21.9 + 5.4 ms |
| **name search** `'headphones'` | 2 | **full table scan** (`LOWER(name) LIKE '%..%' OR LOWER(description) LIKE '%..%'`) | 20,000 → 982 matches → 20 | filesort of 982 + Materialize | 32.7 + 26.6 = **59 ms** (scan runs twice: list + count) |
| product detail id=5 | 1 | PK + `idx_favorites_product_id` | 1 → 1 | none | 0.004 ms (1.7 ms incl. ORM) |
| **my orders, hottest user** (16,347 orders) | 2 | `idx_orders_user_id` lookup | 16,347 → 10 (count: 16,347 covering) | filesort of 16,347 rows | 37.9 + 2.8 = **40.7 ms** |
| my orders, customer050 (725 orders) | 2 | `idx_orders_user_id` | 725 → 10 | filesort of 725 rows | 1.6 + 0.13 ms |
| order creation: product lookup | 1 | PK range (3 ids) | 3 → 3 | none | 0.016 ms |
| auth: `is_revoked()` | **2** (`DELETE` expired + `SELECT`) | DELETE: `type=ALL` on `revoked_tokens` (no index on `expires_at`) | – | – | 1.6 ms |
| auth: user lookup | 1 | PK | 1 → 1 | none | 0.7 ms |

## What the plans show

1. **Sort-after-filter, not index-ordered.** Every list and "my orders" query reads *all* rows that
   match the filter and sorts them to find the top 10/20. There is no index that matches
   `WHERE ... ORDER BY created_at DESC, id DESC`. Cost grows with the size of the category or the
   user's history (16,347 rows for the hottest user).
2. **`count(*)` is a second full pass** over the same filtered set on every request.
3. **The `joinedload(Product.favorites)` + `LIMIT` combination** makes SQLAlchemy wrap the query in a
   derived table (`Materialize` in every list plan) with a `LEFT JOIN favorites`. The favorites table
   is empty in the seed, so its cost is hidden here; it grows with the number of favorites. The
   detail query joins `favorites` the same way.
4. **Name search is a full scan twice** (list and count), 59 ms of DB time per request.
5. **Deep OFFSET** sorts 18,000 rows to return 20.
6. **Auth runs 3 statements per request** (`DELETE` + 2 `SELECT`) and the `DELETE` is a write on every
   authenticated GET. `revoked_tokens` is empty today, so it is cheap now.

## Important caveat: these DB times do not explain the baseline latencies

The k6 baseline shows p50 of 150–240 ms at 20 VUs, but the database work per request above is
0.004–60 ms and mostly under 15 ms. For example, product detail costs 1.7 ms in the database yet its
p50 under load is 153 ms. A CPU sample during a detail-only run (`docker stats`, three samples) showed
`app` at about 121% CPU and `db` at about 14%, with 16 CPUs available. That points to the single
Python worker being the limit for the cheap endpoints, with the DB cost only mattering for the heavy
ones (search, deep page, hottest user's orders). See `optimization_log.md`, entry 0.

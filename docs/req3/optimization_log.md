# Requirement 3 — optimization log (Phase 1)

Rule: measure, change ONE thing, measure again. Numbers come from `loadtest/results/<label>.json`
(k6 profile in `loadtest/k6/main.js`, unchanged between runs). Machine: Windows laptop, Docker
Desktop VM with 16 CPUs / 7.6 GB, one uvicorn worker (not to be changed here: scaling is
Requirement 5). Absolute numbers are only comparable between runs on this machine.

## Entry 0 — Baseline (`before`), unmodified code

Data: 300k seeded orders (+ about 950 created by the harness smoke run and baseline), 20k products.
Full profile: 20 VUs per read scenario (30 s each), `create_order` open-loop at 5/s, mixed
90% read / 10% write with 30 VUs for 60 s. All requests succeeded (0.00% errors in every row).

| endpoint | req/s | p50 ms | p95 ms | p99 ms |
|---|---:|---:|---:|---:|
| list (category filter, page 1–5) | 74.27 | 221.4 | 316.3 | 375.3 |
| list_deep (page 900, offset 17,980) | 13.07 | 243.4 | 339.1 | 394.5 |
| detail | 127.50 | 153.5 | 218.1 | 252.6 |
| search | 81.83 | 237.2 | 342.7 | 408.8 |
| my_orders | 92.10 | 213.6 | 302.0 | 355.4 |
| create_order (5/s open-loop, WRITE cost) | 5.03 | 49.3 | 64.0 | 66.6 |
| mixed_total (30 VUs) | 83.30 | 332.5 | 623.7 | 799.4 |

Per-row `req/s` is `count / scenario duration`. In the closed-loop scenarios latency and req/s are
linked (Little's law), so they move together: a faster server shows lower latency and more req/s.

**Run-to-run noise.** A second, detail-only run (`diag_detail`) gave 122.3 req/s and p50 159.1 ms
against 127.5 req/s and 153.5 ms in the baseline: about 4% variation on the same code. Treat
differences smaller than roughly 5–10% as noise.

**Diagnosis (measured, not assumed).** During the detail-only run `docker stats` showed:
`app` about 121% CPU, `db` about 14%, `inventory-service` about 9%, `inventory-db` 2–6%, k6 8–14%,
on a 16-CPU VM. The detail query costs 1.7 ms in MySQL (EXPLAIN ANALYZE). So for cheap endpoints the
limit is the single Python process, not the database. Consequences for the plan:

* DB-side fixes (indexes, keyset, search) will help the heavy rows (search ≈ 59 ms DB time,
  deep page ≈ 27 ms, hottest user's orders ≈ 41 ms) and reduce DB CPU, but cannot lift the
  per-request Python cost.
* Reducing per-request work in the app (statements per request, ORM loading, JSON building) is what
  can move the cheap endpoints. Candidates, to be confirmed with the query counter (Step 4):
  the 3 auth statements per request, the favorites join, the duplicate `count(*)`.
* Not yet measured: how the app's 121% CPU splits between ORM, pydantic validation and gRPC. I have
  not profiled it and will not claim a split until I do.

## Entry 1 — Move the expired-token purge off the request path

**Hypothesis.** `current()` ran `DELETE FROM revoked_tokens WHERE expires_at < now` on every
authenticated request (3 statements per auth, one a write on a GET). Removing it should cut one
round trip per request and, more importantly, remove a write from the read path (a prerequisite
for sending reads to a replica).

**Change.** `tokens.is_revoked()` is now a primary-key lookup only. `tokens.purge_expired()` does the
cleanup and runs from a background task every `REVOKED_PURGE_INTERVAL_SECONDS` (default 300). This is
behaviour-neutral: an expired JWT is rejected by its own `exp` claim, so the purge is housekeeping.

**Evidence of the effect on statements** (`scripts/query_counts.py`, `DB_QUERY_COUNT=1`):

| request | before | after |
|---|---:|---:|
| `GET /auth/me` | 3 | 2 |
| `GET /products?...` (any limit) | 5 | 4 |
| `GET /products/5` | 4 | 3 |
| `GET /orders?...` (any limit) | 5 | 4 |
| `POST /orders` (3 items) | 12 | 11 |

Counts do not grow with `limit` (1 to 100), so there is **no ORM N+1** in the list endpoints today.

**Throughput/latency** (`--only` runs, same profile; `before` = full-profile baseline):

| run | req/s | p50 ms | p95 ms | p99 ms |
|---|---:|---:|---:|---:|
| detail, before | 127.50 | 153.5 | 218.1 | 252.6 |
| detail, repeat of before (`diag_detail`) | 122.33 | 159.1 | 228.4 | 267.4 |
| detail, after | 119.70 | 162.6 | 240.6 | 293.1 |
| list, before | 74.27 | 221.4 | 316.3 | 375.3 |
| list, after | 79.10 | 207.8 | 301.5 | 360.5 |
| list_deep, before | 13.07 | 243.4 | 339.1 | 394.5 |
| list_deep, after | 13.73 | 232.0 | 326.4 | 384.9 |

All numbers are read from `loadtest/results/{before,diag_detail,c1_purge_detail,c1_purge_list}.json`.

**Result: no measurable improvement.** `detail` moved from 127.5 to 119.7 req/s (-6%) and `list`
from 74.3 to 79.1 req/s (+6%). The two repeat runs of the *unchanged* code differed by 4%, and the
changes go in opposite directions, so both are inside the noise band. I am not claiming a speed-up.
I only have single runs per condition, so I can not give a confidence interval.

**Why it is plausible that nothing changed.** The dropped statement is a ~1.6 ms DELETE on an empty
table, against a per-request cost of roughly 8 ms of Python on one saturated core (entry 0). It is
roughly 1 of 3 auth round trips, not enough to see through the noise.

**Decision: keep.** Not for speed, but because it removes a write from every authenticated GET, which
the read-replica routing needs, and it costs nothing measurable.

**Correctness checks** (`tests/req3/test_auth_purge.py`, marker `req3_phase1`): a logged-out token is
still rejected; a revoked-but-unexpired token is still rejected after a purge; an expired token is
rejected by its own `exp` with no revoked row and no purge; the purge deletes only expired rows
and is idempotent; a request no longer deletes anything and uses exactly 2 auth statements.

**Existing test suite and the two environment-dependent tests.** With the compose environment
(`INVENTORY_MODE=grpc`) `test_db_failure_releases_reservation` and `test_cancel_releases_stock`
fail, because the app swaps in the gRPC gateway while those tests assert on the in-memory fake. This
is **identical on the pre-change code** (`HEAD` built into a separate image and run on the compose
network: the same 2 fail in grpc mode, all 20 pass in fake mode), so it is environmental. Run the unit
suite with `INVENTORY_MODE=fake`. The real gRPC path is covered separately by
`tests/req3/test_grpc_e2e.py` (an order created, rejected for insufficient stock, and cancelled
through the Go service), which runs when `E2E_BASE_URL` is set.
Current status: 25 passed, 2 skipped (the e2e test when `E2E_BASE_URL` is unset, and one skip that
was already there); the e2e test passes against the live stack.

## Entry 1b — Response-snapshot regression tests (DONE)

`tests/req3/test_response_snapshots.py` (marker `req3_phase1`) builds a deterministic catalog (3 categories,
24 products incl. 1 inactive, 2 customers with different favorites, multi-item orders) and compares the JSON
bodies of 15 list variants x 3 users (a, b, admin), 5 details x 3 users and 9 my-orders variants with the golden
files in `tests/req3/snapshots/` (69 files). Golden files were generated from the code BEFORE any query change.
Key order is compared (no `sort_keys`); timestamps and reservation uuids are masked; the only tolerated extra
field is `next_cursor`. Result after the indexes were added: the whole unit suite reports
`28 passed, 2 skipped` (command output, `INVENTORY_MODE=fake`).

## Entry 2 — Composite indexes (APPLIED, MEASUREMENT **INCOMPLETE**, no speed-up claimed)

**Change.** `products(is_active, created_at, id)`, `products(category_id, is_active, created_at, id)`,
`orders(user_id, created_at, id)`; declared in the models and created idempotently by `app/core/migrations.py`
(they exist in the live DB now). `idx_category_id` and `idx_orders_user_id` were left in place.

**What is established (command output captured during the session, not stored in a results file):**
`EXPLAIN ANALYZE` switched from filesort to an index lookup: category list 6.2 ms (`explain_before.md`) ->
0.085 ms; deep page (offset 17,980) 21.9 ms -> 12.9 ms; hottest user's orders page 37.9 ms -> 0.59 ms (the
`count(*)` of that user's 16,350 orders still costs 3.7 ms). The `search` plan did NOT change (still a full table
scan, 41 ms for the page query and 35.6 ms for its count).

**What is NOT established — the k6 effect.** Time-separated single runs are unusable on this laptop: with the same
code and the same indexes, `list` gave 127.57 req/s (`m1_c1_list`) and later 65.97 req/s (`m1_c1r_list`); `search`,
whose plan is unchanged, moved 82.57 -> 70.33 -> 66.53 -> 68.07 req/s. Drift between runs is far larger than the
~4% noise assumed in entry 0. The interleaved A/B/B/A test (`scripts/ab_indexes.sh`, A = the three indexes dropped,
B = present, same time window) finished only for `list`:

| run | cond | list req/s | list p50 ms | list_deep req/s | list_deep p50 ms |
|---|---|---:|---:|---:|---:|
| `ab_idx_list_1A` | no indexes | 63.67 | 255.2 | 11.3 | 281.1 |
| `ab_idx_list_2B` | indexes | 64.07 | 256.2 | 11.3 | 281.8 |
| `ab_idx_list_3B` | indexes | 64.73 | 252.3 | 11.0 | 285.0 |
| `ab_idx_list_4A` | no indexes | 64.93 | 252.4 | 11.0 | 282.6 |

Within this window the indexes made **no measurable difference** to `list`/`list_deep` throughput or p50, although
the SQL got much cheaper: consistent with the app process, not MySQL, being the bottleneck (entry 0). The
`my_orders` A/B has 1 of 4 runs (`ab_idx_my_orders_1A`; `ab_idx_my_orders_2B` was interrupted and is kept as
`.INTERRUPTED.partial`), and the `create_order` A/B (write cost of the indexes) was **not run**. The earlier pair
`m1_base_create_order` (p50 43.0 ms) vs `m1_c1_create_order` (p50 28.7 ms) is time-separated and therefore NOT
evidence about write cost.

**Decision: keep (pending the remaining A/B).** Reason: the plans are strictly cheaper and DB CPU/latency under the
heavier endpoints should fall; but no throughput gain is claimed.

**Method note for everything that follows.** Compare changes only with interleaved A/B/B/A runs in the same window.
Machine info for the drift is unknown (not measured); the host was otherwise idle (`docker stats`, 1-2% CPU).

---

# Session 2 (resumed run) — environment note

The previous session's database was **not** on this machine: the Docker volume of project `trendova-` held the user's own dev
data (86 users, 32 products, 12 orders, no composite indexes). Nothing was deleted or modified there. Req 3 now runs in its own compose
project `trendova-req3` (see the `name:` line in `docker-compose.yml`) with fresh volumes; the old stack is only *stopped* and can be restored with
`docker compose -p trendova- up -d`. The seed was re-run: **2,001 users, 40 categories, 20,000 products, 300,000 orders, 899,773 order items,
20,000 inventory rows** (command output of `scripts/seed.py` and `SELECT COUNT(*)`), 82 s. This machine is slower than the previous one
(`my_orders` about 38 req/s here, about 92 req/s in `before.json`), so absolute numbers of this session are **not comparable** with the entries above.

## Entry 3 — what slows an index down? Index A/B for `my_orders` and the WRITE cost on `create_order` (interleaved A/B/B/A, same window)

A = the three composite indexes dropped, B = present. Run by `scripts/ab_indexes.sh my_orders create_order` (it must run to the end:
it drops and re-creates indexes; its `EXIT` trap re-creates them). Machine drift is real, so only the interleaved results below are used.
(An earlier launch overlapped with other runs, because stale background processes survived; those runs were discarded and the whole script was re-run alone.)

| run | cond | my_orders req/s | p50 ms | p95 ms | p99 ms |
|---|---|---:|---:|---:|---:|
| `ab_idx_my_orders_1A` | no new indexes | 38.83 | 486.5 | 816.1 | 996.8 |
| `ab_idx_my_orders_2B` | indexes | 41.13 | 462.5 | 765.0 | 1178.8 |
| `ab_idx_my_orders_3B` | indexes | 34.87 | 533.8 | 947.4 | 1212.5 |
| `ab_idx_my_orders_4A` | no new indexes | 37.20 | 513.9 | 829.8 | 987.8 |

**Read path: no measurable effect** (A mean 38.0 req/s, B mean 38.0 req/s; the two B runs differ by 6 req/s from each other, more than A vs B).
Same conclusion as for `list` (entry 2): the cost of a request is dominated by the single Python process, not by the SQL.

| run | cond | create_order p50 ms | p95 ms | p99 ms | avg ms | req/s (open loop 5/s) | errors |
|---|---|---:|---:|---:|---:|---:|---:|
| `ab_idx_create_order_1A` | no new indexes | 40.7 | 103.1 | 141.8 | 48.7 | 5.03 | 0 |
| `ab_idx_create_order_2B` | indexes | 35.6 | 99.5 | 152.3 | 43.8 | 5.03 | 0 |
| `ab_idx_create_order_3B` | indexes | 36.1 | 86.2 | 116.8 | 42.1 | 5.00 | 0 |
| `ab_idx_create_order_4A` | no new indexes | 40.2 | 100.4 | 124.4 | 49.1 | 5.03 | 0 |

**Answer to "what slows an index down?" (slide 6).** Every INSERT must also insert a row into every secondary index of the table, and every
UPDATE of an indexed column must move the entry; indexes also take disk and buffer-pool memory. Measured here: the new `orders(user_id, created_at, id)`
index adds **no measurable write latency at 5 inserts/s** (indexed runs were, if anything, 5 ms *faster* at p50: that is noise, not a benefit, because
the two A runs and the two B runs are as far apart as A is from B). Its size is 9.5 MB for 300k rows (`mysql.innodb_index_stats`; for comparison the
primary key is 31.6 MB, `idx_orders_user_id` 10.5 MB, `idx_orders_status` 8.5 MB). The cost exists but is below what a 30 s run at this rate can resolve;
a saturating write test would be needed to expose it, and it was not run. Conclusion: **keep** the composite indexes; the redundant single-column ones are removed
in step 1.4 because the composites cover their lookups (every prefix of a composite index serves the shorter query), which removes real write/space cost for free.

## Method for the one-change-at-a-time entries below (1.3)

Per change: `EXPLAIN ANALYZE` of the SQL the *real application code* emits (`scripts/explain_hot.py`, run inside the previous image and inside the
new image), statement counts (`Com_select` delta on the primary, variant independent; `scripts/ab_endpoint.py`), and a quick interleaved A/B
(`scripts/ab_endpoint.py`: previous image `trendova-req3-prev` on :8020 vs the new image on :8000, ABBA blocks, 3 rounds, one sequential client; a difference
smaller than the round-to-round spread of the same variant is reported as "within noise"). Raw files: `loadtest/results/chg_*.json`, `explain_*.json`.
The unit/snapshot suite (`tests/req3/test_response_snapshots.py`, `tests/test_api.py`) must pass before and after each change (final full run: see STATE.md).

## Entry 4 - (a) favorites: `joinedload(Product.favorites)` -> one `IN` query for the page's product ids

Change: `repository.list_products/get_product` no longer join `favorites`; `repository.favorite_flags(db, user_id, ids)` runs ONE
`SELECT product_id FROM favorites WHERE user_id=? AND product_id IN (page ids)` and `summary()` reads the flags from that set.
EXPLAIN: the page query lost the derived-table wrapper `SELECT anon_1... FROM (SELECT ... LIMIT) LEFT OUTER JOIN favorites` (SQLAlchemy wraps a
LIMITed query that eager-loads a collection); the new favorites query costs 0.02 ms. Statements per request: 4 -> 5 (`chg_a_list`).
A/B (`chg_a_list`): p50 36.5 ms vs 40.4 ms, rounds [37.6, 37.3, 29.0] vs [43.7, 48.7, 27.7] -> **within noise, no gain** (spread 21 ms).
Why it is still kept: the seed has 0 favorites, so the join cost nothing here; with real data a popular product with F favorites made the old query
return F rows per product (row fan-out inside the LIMIT subquery). The new shape is independent of F. Honest summary: neutral on this data, +1 cheap statement.

## Entry 5 - (f) NEW, justified by the EXPLAIN of entry 4: `is_active IS true` defeated the composite indexes

While measuring (a) the page query still showed `sort=YES` and, for "newest page", a full table scan of 20,000 rows although the composite
index `(is_active, created_at, id)` exists. The ORM predicate `Product.is_active.is_(True)` renders `products.is_active IS true`; MySQL cannot use it for
an index range, so it filesorts. Hand-run check on the same data (`EXPLAIN ANALYZE`): `IS true` 2.98 ms + `Sort`; `= true` / `= 1` 0.05 ms `Covering index lookup`
(deep page 19.4 ms -> 9.1 ms). Change: `Product.is_active == True` in `list_products` (renders `= true`).
**This also explains entries 2 and 3**: the composite indexes were never used by the real product-list SQL, which is why the earlier A/B runs saw no effect on `list`.
EXPLAIN of the application's own page query (`explain_a_after` -> `explain_f_after`): category page 14.8 ms (sort) -> 0.115 ms; newest page 53.1 ms (full scan + sort) -> 0.087 ms;
search "wireless" page 132 ms -> 0.78 ms (the index order lets MySQL stop after 128 rows). Interleaved A/B (previous vs new image):
`chg_f_list` p50 **34.1 -> 16.0 ms (2.14x)**, rounds [36.0, 28.7, 39.3] vs [14.7, 16.8, 16.4] (no overlap); `chg_f_search` p50 **149.5 -> 71.9 ms (2.08x)**, rounds [163, 141, 135] vs [72, 65, 89].
The rest of a request is Python (auth, ORM, JSON), so the end-to-end gain is smaller than the SQL gain. Snapshot suite: pass.

## Entry 6 - (b) `count(*)` without the derived-table wrapper

`q.count()` emitted `SELECT count(*) FROM (SELECT products.id, products.name, ... FROM products WHERE ...) AS anon_1`. Now
`q.with_entities(func.count(Product.id)).order_by(None).scalar()` -> `SELECT count(products.id) FROM products WHERE ...` (products list and orders list).
EXPLAIN (count statement): newest page 25.9 ms -> 7.8 ms, deep page 13.5 ms -> 8.4 ms, category 1.26 -> 1.08 ms, hottest user's order count 7.3 -> 5.9-8.4 ms (noisy).
A/B: `chg_b_list` p50 17.5 vs 20.1 ms and `chg_b_orders` 23.3 vs 24.0 ms -> **within noise**. Statements unchanged (5 and 4). Kept: strictly cheaper SQL, no behaviour change.

## Entry 7 - (c) my_orders: `joinedload(order_items)` -> `selectinload`

The old query joined `order_items` inside a LIMIT subquery (derived table + sort, `scan=YES sort=YES`, rows=28 for 10 orders). Now: page query (index lookup, 10 rows, 1.15 ms),
count, and `SELECT ... FROM order_items WHERE order_id IN (...)` (0.19 ms). Statements per request: 4 -> 5 and **constant for limit 10/50/100**
(`chg_c_orders_10/50/100`, test `test_my_orders_query_count_is_constant_in_page_size`). A/B: p50 20.6 vs 19.7 / 28.9 vs 31.6 / 36.2 vs 37.2 ms -> **within noise**
at every page size. Kept: removes the fan-out, one more cheap statement.

## Entry 8 - (d) dashboard stats: `by_status()` executed 5 times

Fixed (one GROUP BY, shared by the five statuses): 10 SELECTs -> 6 (EXPLAIN list). Each of the 5 queries scans the status index (119-234 ms each, about 0.75 s in total, 4/5 of it saved).
`chg_d_dashboard`: p50 13.34 s vs 12.96 s (3 requests each) -> **within noise (-3 %), as expected**. **Finding (not fixed, out of scope):** the dashboard takes 13-20 s because
`top_products` aggregates all 860k `order_items` rows with a join and a filesort (14.5-30.8 s in `EXPLAIN ANALYZE`), plus `revenue` (190-525 ms) and `recent_orders` (441-1,039 ms, full scan + sort of 300k orders).
A summary table or a short-TTL cache would fix it; it is an admin-only page and it is not in the k6 profile. It is one more reason to serve it from the replica (a long read that
should not compete with checkout on the primary).

## Entry 9 - (e) keyset pagination (`cursor`)

Additive: `GET /products?cursor=<next_cursor>`; every list response carries `next_cursor` (null on the last page); `page` keeps working; a cursor issued for another sort -> 422 `INVALID_CURSOR`.
Tests `tests/req3/test_keyset.py` (9): the cursor walk equals the offset pages for 6 sort/order combinations with deliberate ties, `page` is ignored when a cursor is given, bad cursors rejected.
First attempt used the row constructor `(created_at, id) < (v, id)`: MySQL only applied it as a *filter* (rows examined 18,000, 44 ms, same as OFFSET); the OR form
`created_at < v OR (created_at = v AND id < last)` is an index range scan: page query **44.2 ms -> 0.086 ms** (EXPLAIN, rows 18,000 -> 20).
A/B on the same container (`chg_e_keyset`, offset `page=900` vs cursor): p50 **97.6 -> 31.9 ms (3.06x)**, rounds [85, 124, 73] vs [33, 50, 19]. The count statement still runs (total/pages stay in the contract).
k6: `DEEP_PAGE_MODE=keyset` (`scripts/bench.py --deep-page-mode keyset`).

## Entry 10 - 1.4 drop the redundant single-column indexes (separate migration)

`app/core/migrations_req3_indexes.py up|down|status` (records `req3_002_drop_redundant_indexes` in `schema_migrations`). It refuses to drop an index unless a composite index leads with the same column.
Checked first (information_schema): `fk_orders_user_id` is served by `idx_orders_user_created` and `fk_products_category_id` by `idx_products_cat_active_created`. Ran `status` -> `up` -> `down` -> `up`:
the downgrade recreates both indexes, final state = dropped. EXPLAIN re-check on the app's own SQL after the drop (`explain_idx_dropped.json`): category page 0.128 ms, newest 0.071 ms,
keyset 0.086 ms, search 0.53 ms, hottest user's orders page 0.93 ms: unchanged, all index lookups, no filesort. Models no longer declare the two indexes.
Space freed: 1.5 MB + 10.5 MB (`mysql.innodb_index_stats`), and one B-tree less per INSERT/DELETE on `orders` and `products`.
Note for A/B: the "before" state of the benchmarks restores the ORIGINAL index set (`scripts/ab_runner.py set_indexes(False)`: composites dropped, the two single-column indexes present).

---

## Entry 11 - PART 2: GetStockBatch (cross-service N+1)

Before: the list-with-stock path would need one `GetQuantity` gRPC call per product (N calls). Now `GetStockBatch(product_ids[]) -> items[{product_id, available, found}]` (additive in `proto/inventory.proto`, every
existing RPC kept): ONE SQL query `WHERE product_id = ANY($1)`, duplicate ids collapsed (first-seen order), at most 500 ids (more -> `INVALID_ARGUMENT`), non-positive id -> `INVALID_ARGUMENT`, empty request -> empty response without
touching the database, **unknown id -> `found=false, available=0`**, server-side deadline of 2 s on top of the client's 2 s per-call deadline (same mapping to `InventoryUnavailableError` as the single call). Stubs regenerated in containers
(Go: `golang:1.22-alpine` + protoc-gen-go v1.34.2 / protoc-gen-go-grpc v1.5.1; Python: `grpc_tools` in the Dockerfile). The Python client reuses the ONE gRPC channel of the gateway and chunks requests above `INVENTORY_BATCH_MAX` (200) ids.
Exposed as `GET /products?include_stock=true` (opt-in, default off; every item gets `stock: {quantity, status}`); the naive per-item path exists only as `stock_mode=naive` on the diagnostics instance (`DIAG_ALLOW_STOCK_MODE=1`) and in the tests.
Go unit tests (dedupe, empty, invalid, max batch): pass. Python: `tests/req3/test_get_stock_batch.py` (10 tests against the real Go service, incl. service stopped and restarted).

gRPC calls per request (header `X-Inventory-Rpc-Calls` of the diagnostics instance): naive **10 / 50 / 100**, batch **1 / 1 / 1** for limit 10 / 50 / 100.
Interleaved A/B on the same container (`stock_naive_vs_batch_*.json`, 3 rounds x 30 requests):

| limit | naive p50 ms | batch p50 ms | ratio | verdict |
|---:|---:|---:|---:|---|
| 10 | 34.9 | 23.4 | 1.49x | within noise (rounds overlap: [32, 35, 44] vs [21, 35, 22]) |
| 50 | 97.2 | 26.0 | 3.74x | batch faster |
| 100 | 147.4 | 32.3 | 4.57x | batch faster |

Honest reading: at 10 items the saving is small and not separable from noise on this laptop (a gRPC call on the compose network is about 2-3 ms); it grows linearly with N because the naive path pays one round trip per item.
Failure behaviour is the same as the single call (2 s deadline, `InventoryUnavailableError`, the request still answers 200 with `status: "unavailable"`).

## Entry 12 - PART 3: MySQL read replica, Redis, read-your-writes

Replica from the SAME image tag (`mysql:8.0`); primary restarted with `server-id=1, log-bin, ROW, GTID ON, enforce-gtid-consistency` (its data volume untouched). The replica is created from a consistent dump
(`mysqldump --single-transaction --set-gtid-purged=ON`) by the one-shot `replica-init` service and then `CHANGE REPLICATION SOURCE TO ... SOURCE_AUTO_POSITION=1, GET_SOURCE_PUBLIC_KEY=1; START REPLICA`.
`read_only` / `super_read_only` are enabled with `SET PERSIST` by the init script (they cannot be command-line flags because the entrypoint must write while initialising a fresh data directory).
Healthcheck = both replication threads running + `super_read_only=1`. Redis: `redis:7-alpine`, `maxmemory 256mb`, `allkeys-lru`, no persistence; `app/core/redis.py` (sync redis-py, 150 ms timeouts, `trendova:` prefix, 2 s circuit breaker, every call fail-open).
App: two engines (`DATABASE_URL`, `DATABASE_REPLICA_URL`/`DATABASE_REPLICA_HOST`), flag `USE_READ_REPLICA`; writes, transactions, auth reads, cache fills, product list/detail and the favourites lookup stay on the PRIMARY; my orders, product search, admin lists and dashboard stats use the replica unless the user holds `trendova:ryw:{id}`.
Replica lag under load (`scripts/measure_lag.py`, `replica_lag.json`): k6 `create_order` 5/s: max **1 s** (mean 0.11 s); 8 closed-loop buyers at 17.5 orders/s: max **1 s**, caught up 0.6 s after the load stopped -> `RYW_WINDOW_SECONDS=5` (> 2x margin). Full design, failure modes and the "not guaranteed" list: `docs/req3/replica.md`.
Verified by `tests/req3/test_replica.py` (6 tests: replica read-only and no local GTID, reads actually reach the replica, replica down, Redis down, read-your-writes under `SOURCE_DELAY=3`).

## Entry 13 - PART 4: Redis cache-aside + ETag

Policy table, keys, TTLs and invalidation rules: `docs/req3/cache_policy.md`; HTTP side: `docs/req3/http_cache.md`. Implementation: `app/core/cache.py`, `app/core/http_cache.py`, `app/modules/products/http.py`.
Decisions worth remembering: (1) list pages are cached WITHOUT the user's favourites and the body+ETag are stored together; a request with favourites or `include_stock` merges the per-user / live data and gets the hash of the bytes it really sends;
(2) the detail cache holds only the static part, its entry remembers the category-version (`catver`) it was built under, so a category rename cannot leave a stale name; (3) `INCR products:ver` after the commit, never KEYS/SCAN; (4) fills read the PRIMARY;
(5) `X-Cache: HIT|MISS|BYPASS`, counters at `GET /internal/cache-stats` (admin); (6) `GZipMiddleware` + a small `MergeVary` ASGI middleware (GZip appends its own `Vary: Accept-Encoding`; duplicates are merged);
(7) the security middleware no longer overwrites an endpoint's own `Cache-Control` (it still sets `no-store` on every other API response).
Measured at the HTTP level: first list GET `MISS`, repeats `HIT`; after an admin edit the next GET is a `MISS` with the new price; stock changes are visible at once while the detail's static part is a `HIT`; `If-None-Match` -> 304 with 0 body bytes;
gzip keeps the same ETag (list page 3.6 KB identity vs 0.3 KB gzip in the demo). Honest note: for the detail endpoint the cache saves almost nothing on this setup (a primary-key lookup in MySQL costs about as much as the Redis round trips), because stock (gRPC) and `is_favorite` must be fetched on every request anyway; the list cache is where it helps.
Tests: `test_cache.py` (8), `test_etag.py` (6), `test_freshness.py` (4); all pass (see STATE.md for the latest full run).

## Entry 14 - a bug the FIRST final benchmark session exposed (session aborted and re-run)

In the first interleaved session `final_V1_r1` (new code, replica OFF, cache OFF) showed `my_orders` at **0.67 req/s, p50 30,167 ms, 60 % errors** while V0 and V2 were normal
(files kept in `loadtest/results/_aborted_session1/`, not used anywhere in the report). Cause (found from the numbers: 30 s = SQLAlchemy `pool_timeout`, only V1 affected, V2 reads another pool):
with `USE_READ_REPLICA=false` the new `read_db` dependency opened a **second primary session** while the auth dependency still held the first one for the whole request. With 20+ concurrent requests every request
held one of the 15 pooled connections and waited for a second one: a pool deadlock until `pool_timeout`. The same shape existed for product search (and for any read routed to the primary because of a marker or a dead replica).
Fix: `route_read(..., primary=<the request's own session>)` returns that session instead of opening a new one (`owned=False`, never closed twice); `read_db`, the search path and the cache-fill path use it.
Regression tests (live): `test_no_connection_pool_exhaustion_when_the_replica_is_off` (40 concurrent `/orders` on the flags-off instance, all 200 in < 25 s) and `..._when_the_replica_is_down`.
Lesson recorded: never hold two connections of the same pool in one request; a benchmark of EVERY variant (not only the final one) is what found it. The whole session was re-run on the fixed image.

## Entry 15 - dashboard `top_products` (the 13-20 s finding of entry 8)

Change: `orders.service.top_products` caches the aggregate in Redis (`trendova:dashboard:top_products`, 300 s, fail-open). Status: **code written, syntax checked only; NOT VERIFIED**
(no EXPLAIN/latency measurement and no test after the change). Expected effect: first call still 13-30 s, later calls skip that query; the other dashboard queries (revenue, recent orders, by_status) are unchanged and still cost 0.1-1 s each.

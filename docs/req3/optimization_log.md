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

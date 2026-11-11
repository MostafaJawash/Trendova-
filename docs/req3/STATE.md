# Requirement 3 — Phase 1 handoff state

Written when work was paused in the middle of milestone M1. Facts only; every number is copied from a file in
`loadtest/results/` (or marked "command output"). Nothing is committed. `Trendova-/` (untracked nested folder) was not touched.
Branch: `perf/part1-db-replica`.

## 1. Plan and status

The Phase 2 prompt (Redis, ETag, final proof) is **NOT to be executed yet**; its pre-check must be re-run when Phase 1 is finished.

| Milestone | Status |
|---|---|
| Pre-check of Phase 1 | Done: Phase 1 was found incomplete (see git history of this conversation), Option A chosen |
| **M1** indexes, favorites join, duplicate count, keyset, name search, order_items selectinload, snapshot tests, `after_indexes` x2, index write cost | **In progress** (see below) |
| M2 GetStockBatch (proto + Go + Python stubs, `include_stock=true`, tests) | Not started |
| M3 MySQL primary+replica, Redis container + `app/core/redis.py`, routing, `USE_READ_REPLICA`, `ryw:{user_id}`, `after_db` x2 | Not started |
| M4 tests for batch/replica/read-your-writes, `run_phase1.py`, Makefile, clean PASS | Not started |

### M1 detail
| Item | State |
|---|---|
| Response-snapshot tests (`tests/req3/test_response_snapshots.py`, 3 tests, golden files in `tests/req3/snapshots/`, 69 files, generated from the UNCHANGED code) | **Done**, passing |
| Composite indexes (3) | **Applied** in code and live DB; k6 measurement **incomplete** (see section 3) |
| Favorites join -> EXISTS column | Not started (`repository.py` unchanged) |
| Duplicate/redundant `count(*)` | Not started. Note: no literally duplicated count statement exists today (4 statements per list request = 2 auth + page + count); the plan is to skip the count pass when the page is short |
| Keyset pagination (`cursor` / `next_cursor`, additive) | Not started. `loadtest/k6/main.js` already supports `DEEP_PAGE_MODE=keyset` and expects `next_cursor` |
| Name search (`LOWER()` removal) | Not started. FULLTEXT deliberately not chosen (changes substring semantics), see open questions |
| `selectinload(order_items)` for my_orders | Not started |
| `after_indexes` full run x2 | Not started |
| Index write-cost measurement (create_order A/B) | Not started |

Other uncommitted work from earlier in the task (Phase 1 start): auth purge moved to a background task, query counter
(`DB_QUERY_COUNT`), `scripts/{bench,seed,query_counts}.py`, k6 harness, `docs/req3/{explain_before,optimization_log}.md`,
`tests/req3/{test_auth_purge,test_grpc_e2e}.py`, `pytest.ini`.

## 2. Current system state

* `docker compose ps`: `app` (healthy), `db` (healthy), `inventory-db` (healthy), `inventory-service` (up). `GET /health` -> 200. No k6 container left. No Redis, no replica (not built yet).
* App image contains the three indexes' model/migration code (built with `docker compose up -d --build app`); no other Phase 1 query change is in the image.
* MySQL indexes that exist now (from `information_schema`): `orders`: `idx_orders_status(status)`, `idx_orders_user_id(user_id)`, `idx_orders_user_created(user_id,created_at,id)`; `products`: `idx_category_id(category_id)`, `idx_products_active_created(is_active,created_at,id)`, `idx_products_cat_active_created(category_id,is_active,created_at,id)`.
  The A/B script was killed (not exited normally), so its restore trap did not run; the state above was verified afterwards and is the intended one (all three new indexes present).
* Env flags: none toggled. `DB_QUERY_COUNT` defaults to 0 in compose. `INVENTORY_MODE=grpc` in compose; unit tests need `INVENTORY_MODE=fake`.
* Data (command output): orders 301,251, products 20,001 (one extra is the soft-deleted product from the gRPC e2e test), favorites 0.
* Unit suite last run (after the indexes): `28 passed, 2 skipped` in fake mode.

## 3. Result files (`loadtest/results/`)

All runs: profile unchanged, 0 errors in every row. Single laptop, single worker. **Machine drift between time-separated runs is much larger than the earlier ~4% estimate** (e.g. `list` with identical code: 127.57 req/s in `m1_c1_list`, 65.97 in `m1_c1r_list`); compare only interleaved runs.

| File(s) | Represents | Validity |
|---|---|---|
| `before` | Full-profile baseline (code before any change) | Valid baseline, but old time window |
| `diag_detail` | Detail-only repeat on baseline code (noise check) | Diagnostic |
| `c1_purge_detail`, `c1_purge_list` | After moving the token purge off the request path | Single runs |
| `m1_base_{create_order,list,search,my_orders,detail}` | M1 start state (purge change only, no indexes), same session | Single runs, time-separated |
| `m1_c1_{create_order,list,search,my_orders}` | After the indexes, one run each | Single runs, **drift-confounded; do not use for conclusions** (the +54% `list` there is not reproducible) |
| `m1_c1r_{search,my_orders,list}`, `m1_c1r_{search2,my_orders2}` | Repeats after the indexes | Diagnostic: evidence of drift (`search` plan unchanged: 70.33 -> 66.53 -> 68.07 req/s) |
| `ab_idx_list_{1A,2B,3B,4A}` | Interleaved A/B/B/A, A = 3 indexes dropped, B = present | **Valid.** list req/s 63.67 / 64.07 / 64.73 / 64.93: no measurable effect |
| `ab_idx_my_orders_1A` | A/B run 1 of 4 (A) | Valid single run, alone it proves nothing |
| `ab_idx_my_orders_2B.INTERRUPTED.partial` | Run killed mid-way (387 requests instead of ~2,100) | **Partial; its req_per_s is invalid.** Kept for the record only |
| (not run) `ab_idx_my_orders_{3B,4A}`, `ab_idx_create_order_*` | — | Missing |

Optimization log: `docs/req3/optimization_log.md` entries 0, 1, 1b (snapshot tests, done) and 2 (indexes: applied, measurement incomplete, no speed-up claimed).
Older doc: `docs/req3/explain_before.md` (EXPLAIN before any change). EXPLAIN-after numbers for the indexes are only in the log entry as "command output", not in a file.

## 4. Commands to resume

```bash
cd "c:/Backend Projects/Trendova-"
docker compose ps                                   # all 4 services up/healthy
docker compose up -d --build app                    # only after changing app code (applies migrations)

# unit + snapshot suite (tests are not in the image: bind-mount them)
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -v "$(pwd)/tests:/app/tests" -v "$(pwd)/pytest.ini:/app/pytest.ini" \
  -e INVENTORY_MODE=fake app python -m pytest -q tests -p no:cacheprovider

# finish the index A/B (re-runs my_orders 1A..4A with the same labels, i.e. overwrites ab_idx_my_orders_1A; then create_order)
bash scripts/ab_indexes.sh my_orders create_order   # ~4 runs/endpoint, ~1 min each; do NOT kill it mid-run (it drops/creates indexes)

# a single measured run
py scripts/bench.py --label <label> --only list|detail|search|my_orders|create_order|mixed
py scripts/bench.py --compare before m1_base_list      # side-by-side
```
Next code step: M1 change 3, favorites `EXISTS` column in `app/modules/products/repository.py` (+ `summary()` in `service.py`), then measure it with an interleaved A/B.

## 5. Open questions

1. Name search: keep substring semantics (current plan: only drop `LOWER()`, expect little gain) or add an opt-in FULLTEXT mode?
2. Keep the now-redundant `idx_orders_user_id` / `idx_category_id` (they cost writes) or drop them after the write-cost test?
3. The label `after_indexes` is planned to mean "state after ALL M1 changes". Confirm.
4. Per-change measurement needs an A/B method for code changes (not only DB toggles): proposal is a second app container from the previous image on another port, alternating k6 against both. Approve?
5. Cause of the run-to-run drift is unknown (not measured); it limits what the final before/after table can claim.

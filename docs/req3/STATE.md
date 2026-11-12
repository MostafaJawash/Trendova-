# Requirement 3 - final state

Branch `req3-resume` (created from `origin/main`; nothing committed or pushed). Compose project `trendova-req3` (fresh volumes). The user's old dev volumes (project `trendova-`) were never touched:
restore with `docker compose -p trendova- up -d`. Seed: 2,001 users / 20,000 products / 300,000 orders (+ benchmark orders, now about 307k) / ~900k items.

## Done (evidence)
| Part | State | Evidence |
|---|---|---|
| 1.1 index A/B | done | `ab_idx_*.json`, log entry 3 |
| 1.2 snapshots | pass | `tests/req3/test_response_snapshots.py` |
| 1.3 (a)-(e) + extra (f) `is_active IS true` fix | done, one entry each | log entries 4-9, `chg_*.json`, `explain_*.json` |
| 1.4 drop redundant indexes | done, up/down/up tested | `app/core/migrations_req3_indexes.py`, entry 10 |
| 1.5 hygiene | done | `tests/conftest.py`, `scripts/req3_cleanup.py` |
| 2 GetStockBatch | done, Go stubs regenerated, service rebuilt; gRPC calls N -> 1 | entry 11, `test_get_stock_batch.py` |
| 3 replica + Redis + RYW | done; max lag 1 s | `replica.md`, `replica_lag.json`, entry 12 |
| 4 cache + ETag | done | `cache_policy.md`, `http_cache.md`, entry 13 |
| 5 tests | 64 selected by `-m "req3_phase1 or req3_phase2"` | `TESTS_MAP_AR.md` |
| 6 final interleaved bench | done (V0..V4 x2, control start/end, cold, k6 freshness: stale_reads 0 over 528 checks) | `loadtest/results/final_*.json` |
| 7 Arabic report | done, tables generated | `REPORT_AR.md` (`scripts/make_report.py`) |
| 8 phase runners | `run_phase1.py` PASS (153 s), `run_phase2.py` PASS (194 s) | run in an earlier session |
| 9 demo | full demo: OVERALL PASS in 496 s (8.3 min, budget 8 min: slightly over); `--quick` PASS in 141 s | `/tmp/demo_full1.log`, `loadtest/results/demo_last.json` |
| 10 tests map | done | `TESTS_MAP_AR.md` |

The "4 failing tests" (stock batch x2, `detail_by_pk`, `keyset_deep_page`) were fixed earlier: Go service rebuilt with GetStockBatch, keyset uses the OR form, live plan tests now EXPLAIN the application's own SQL. Latest marker run: 64 passed, 0 failed, 0 skipped.

## Honest findings
* The single Python worker (CPU 89-104 % in every variant) is the bottleneck; DB wins shrink end-to-end. Only `search` (+209 %), `list` and `list_deep` (+46 %) are above the measured noise; `detail`, `my_orders`, `create_order`, `mixed_total` are within noise (no claim). See `REPORT_AR.md`.
* A first benchmark session exposed a connection-pool deadlock (replica off); fixed and the whole session re-run (entry 14, aborted files in `loadtest/results/_aborted_session1/`).
* Full demo takes 8.3 min (budget 8); `--quick` 2.4 min.

## NOT VERIFIED
* Dashboard `top_products` Redis cache (entry 15): code only, no test or measurement after the change; unit suite (`tests/test_*.py`) not re-run after the pool fix and this change.
* `docs/req3/REPORT_AR.md` was generated from the final session; the demo `--from-results` without Docker was not exercised in this session.
* Two further full-demo rehearsals were skipped on request.

## Commands
```bash
docker compose up -d --build            # stack
docker compose --profile test build tester   # rebuild after every app change
docker compose --profile test run --rm --no-deps tester tests -m "req3_phase1 or req3_phase2" -q
python scripts/demo_req3.py [--quick|--from-results]
python scripts/bench_final.py           # about 1 h, exclusive use of Docker
python scripts/req3_cleanup.py          # remove req3_test_/req3_demo_/req3_k6_ rows
```

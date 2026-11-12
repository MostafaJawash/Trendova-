# Cache policy (Requirement 3)

Server cache = Redis (cache-aside, `app/core/cache.py`). HTTP cache = ETag / `If-None-Match` (`app/core/http_cache.py`).
Flags: `CACHE_ENABLED`, `ETAG_ENABLED` (both default off in code, on in the final compose service `app`).

## What is cached, what is not

| What | Key | TTL | Invalidation | Why |
|---|---|---|---|---|
| Product **list page** (static body: id, category_id, name, description, price, image_url, `next_cursor`, totals) | `trendova:products:list:v{N}:{hash(params)}` where `N` = value of `trendova:products:ver` | 60 s ±10 % (`CACHE_LIST_TTL_SECONDS`, `CACHE_TTL_JITTER`) | Any product or category mutation does `INCR trendova:products:ver` **after the DB commit** → every old list key becomes unreachable at once (O(1), no `KEYS`/`SCAN`); old keys die by TTL/LRU | Lists are read far more often than written; the query is the most expensive read; a version namespace makes invalidation one command |
| Product **detail, static part** (name, description, price, image_url, category) | `trendova:products:detail:{id}` (value also carries the category-version it was built under) | 300 s ±10 % (`CACHE_DETAIL_TTL_SECONDS`) | `DELETE` the key after an update/delete of that product (after commit); a category create/update/delete also bumps `trendova:products:catver` so every cached detail (which contains the category name) is rejected on the next read | Detail is the hottest read; its static fields change rarely |
| Stampede lock | `trendova:lock:products:...` | `SET NX PX 5000` | Released by the winner; expires by itself after 5 s | One DB fill per cold key; losers wait ≤ 600 ms then fall through to the DB |
| Read-your-writes marker | `trendova:ryw:{user_id}`, `trendova:ryw:products` | `RYW_WINDOW_SECONDS` (5 s) | Expires by itself | Not a cache of data: tells the router to read the primary (see `replica.md`) |
| **Stock / availability** | — | **never cached** | — | It is the Requirement 2 race-condition guarantee. Detail and `include_stock=true` fetch it from the warehouse on **every request** and merge it into the response |
| `is_favorite` (per user) | — | never cached | — | User-specific. Merged per request from **one** `favorites` query on the primary for the page's product ids |
| Dashboard `top_products` aggregate | `trendova:dashboard:top_products` | 300 s | none (expires) | The query scans about 900k `order_items` rows (14-30 s measured); admin-only aggregate that may be stale; fail-open (no Redis = the slow query runs). **NOT VERIFIED after the change (code only)** |
| Orders, my orders, dashboard stats | — | never cached | — | User-specific / aggregates; served by the replica (or primary right after a write) |
| Auth data (users, tokens, revoked tokens) | — | never cached | — | Always read from the primary; a logout / role change must take effect immediately |
| Admin view of a product (extra fields) | — | `X-Cache: BYPASS` | — | Different shape; low traffic |
| Any write path | — | not applicable | — | Writes go to the primary and invalidate |

## Rules that make it correct

1. **Invalidate only after the commit.** If the DB transaction fails nothing is invalidated and nothing was changed
   (test: `test_list_uses_a_version_namespace_and_failed_update_does_not_invalidate`). Invalidating *before* the commit would let
   a concurrent reader re-fill the cache with the old row and keep it for a whole TTL.
2. **Cache fills read the PRIMARY, never the replica.** Right after an invalidation the next request refills the cache. If it read
   a replica that is 1–3 s behind it would store the *old* row under the *new* version and serve it for the whole TTL, which would
   make the edit invisible although the invalidation worked. The primary is the only source that is always current.
3. **Fail-open.** A Redis error or timeout (150 ms) is logged as a warning and the request is answered from the database
   (`X-Cache: BYPASS`); never a 500. A 2 s circuit breaker avoids paying the timeout on every request while Redis is down.
   If an invalidation cannot be sent (Redis down) it is remembered in the process and retried before the next cache read; Redis
   itself has no persistence, so a restarted Redis starts empty.
4. **Stampede protection.** On a miss the request takes `SET lock NX PX 5000`; the winner fills the key, the others poll for ≤ 600 ms and
   then fall through to the database themselves (test: 20 concurrent cold requests → exactly 1 fill).
5. **Bounded memory.** Redis runs with `maxmemory 256mb` and `allkeys-lru`.
6. TTLs carry ±10 % jitter so keys created together do not expire together.

## Observability

* Response header `X-Cache: HIT | MISS | BYPASS` on product list and detail.
* `GET /internal/cache-stats` (admin only): `hit`, `miss`, `bypass`, `fills`, `stampede_waits`, `stampede_fallthrough`,
  `invalidations`, `errors`, `hit_ratio` (counters are per application worker; the final setup has one worker).
  `POST /internal/cache-stats/reset` zeroes them.

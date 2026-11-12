# MySQL read replica and read-your-writes (Requirement 3)

## Topology

```
                writes, transactions, every auth read, cache fills
   app  ------------------------------------------------------------->  db  (primary, server-id=1, log-bin, ROW, GTID ON)
    |                                                                         |  binlog (GTID, auto-position)
    |  stale-tolerant reads (my orders, product search,                       v
    |  admin lists, dashboard stats) when no RYW marker           db-replica (server-id=2, relay-log, GTID ON,
    +------------------------------------------------------------->           read_only=ON, super_read_only=ON)
    |
    +--> redis  (`trendova:ryw:{user_id}`, `trendova:ryw:products`, cache)
```

* Same image tag for both (`mysql:8.0`). Primary flags (docker-compose.yml): `--server-id=1 --log-bin --binlog-format=ROW --gtid-mode=ON --enforce-gtid-consistency=ON`.
  Replica: `--server-id=2 --relay-log --gtid-mode=ON --enforce-gtid-consistency=ON --log-replica-updates`, and `read_only` / `super_read_only` set with
  `SET PERSIST` by the init script (they cannot be passed as flags: the image entrypoint must write while it initialises a fresh data directory;
  `SET PERSIST` survives restarts, and the healthcheck requires `@@super_read_only = 1`).
* **Initialisation** (`scripts/replica_init.sh`, one-shot service `replica-init`, idempotent): the primary already held the big dataset, so the replica is
  loaded from a **consistent dump** (`mysqldump --single-transaction --set-gtid-purged=ON`), then
  `CHANGE REPLICATION SOURCE TO SOURCE_HOST='db', SOURCE_USER='repl', SOURCE_AUTO_POSITION=1, GET_SOURCE_PUBLIC_KEY=1; START REPLICA`.
  A dedicated `repl` user (REPLICATION SLAVE only) is created on the primary. The primary's data volume was not touched.
* Healthcheck of `db-replica` (`scripts/replica_health.sh`): `Replica_IO_Running = Yes` and `Replica_SQL_Running = Yes` and `super_read_only = 1`.

## Why GTID

With GTIDs every transaction has a global id (`server_uuid:n`). The dump carries `GTID_PURGED`, and `SOURCE_AUTO_POSITION=1` lets the replica tell the primary
"I already have these, send me the rest" instead of us writing a binlog file name and position by hand. Re-pointing or re-building a replica, and proving that
**no transaction ever originated on the replica** (every executed GTID has the primary's UUID: `tests/req3/test_replica.py::test_writes_never_reach_the_replica_directly`), are
one-liners. ROW format makes the replicated change deterministic (no dependence on the SQL text or `NOW()`).

## Routing (`app/core/database.py`, `app/core/dependencies.py`)

| Goes to the **primary** | May go to the **replica** (`USE_READ_REPLICA=true`, no marker) |
|---|---|
| every write and transaction | `GET /orders` (my orders and the admin order list) |
| every auth read (login, token revocation, user lookup) | product **search** (`?search=`) when the cache is off |
| **cache fills** (see `cache_policy.md`) | `GET /users` (admin list) |
| product list (no search) and product detail | `GET /dashboard/stats` |
| the favourites lookup merged into list/detail | |

`USE_READ_REPLICA=false` puts everything on the primary. Two SQLAlchemy engines are built from `DATABASE_URL` and `DATABASE_REPLICA_URL` (or `DATABASE_REPLICA_HOST`).

## Read-your-writes (RYW)

Problem: a replica applies changes a moment after the primary commits them. A user who creates an order and immediately opens "my orders" could not see it.

Design: after any **successful commit** by user U (create order, order status change, admin product/category edit, favourite add/remove) the app sets
`trendova:ryw:{user_id}` in Redis with a TTL of `RYW_WINDOW_SECONDS` (default **5**). For an order status change the marker is set for the order's owner **and** the acting admin; a product or category
edit also sets `trendova:ryw:products`, which sends product *search* to the primary for the window (so a rename is findable at once). A read by a user who holds the marker goes to the **primary**;
the marker expires by itself, by which time the replica has caught up.

**The window must exceed the maximum lag.** Measured with `scripts/measure_lag.py` (`loadtest/results/replica_lag.json`, `Seconds_Behind_Source` sampled about twice a second):

| load | observed lag |
|---|---|
| fixed k6 `create_order` scenario, 5 orders/s for 30 s (131 samples) | max **1 s**, mean 0.11 s, 14 samples above 0 |
| 8 closed-loop buyers at the maximum the single worker sustains (525 orders, 17.5 orders/s, 35 samples) | max **1 s**, mean 0.11 s; the replica was fully caught up **0.6 s** after the load stopped |

`Seconds_Behind_Source` has a 1 s resolution, so "1 s" means "below about 1-2 s". The default of 5 s leaves a margin of more than 2x over anything measured. If the primary write load grows (Requirement 5)
re-measure and raise `RYW_WINDOW_SECONDS`.

## Failure modes

| Failure | Behaviour |
|---|---|
| Replica container down / unreachable | The first read finds the connection dead (`pool_pre_ping`), logs a warning and opens a 5 s circuit breaker; every read uses the primary, never a 500 (`test_replica_down_is_still_served_from_the_primary`). It returns by itself after the breaker window once the replica is back. |
| Redis down | A read cannot prove it is fresh, so it is treated as "marker present" -> primary (`test_redis_down_is_still_served_from_the_primary`). Marker writes are skipped silently. |
| Replica lagging beyond the window | Only readers *without* a marker can see stale data (the lag is deliberately made visible with `SOURCE_DELAY=3` in the tests). |
| Replication broken (SQL error) | The healthcheck turns unhealthy; reads still go to the replica until the breaker sees an error, so monitor it. A broken replica serves old data: not handled automatically. |

## What is NOT guaranteed

* **Only the author's own reads** are fresh. Another user (or the admin) may see data up to the replication lag (measured about 1 s, window 5 s) old on the replica-routed endpoints.
* Read-your-writes covers reads that go through the router; **monotonic reads across the window boundary** are not guaranteed: when the marker expires the user's next read may hit a replica that is still a little behind if the lag exceeded the window.
* The marker is per **user**, not per session or device: two devices of the same user share it (good), two different users do not (by design).
* A process restart of Redis loses the markers (no persistence): reads fall back to the primary only while Redis is unreachable, not while it is up but empty. A write in the last 5 s before a Redis restart is therefore not protected.
* Stock is not in MySQL at all (Postgres via gRPC), so it is never affected by replica lag.

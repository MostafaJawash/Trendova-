# Requirement 4 state

## Done

* PART 1 implementation and live verification: RabbitMQ topology, durable email queue/retry queues/DLQ, transactional outbox, worker, SMTP sender and idempotency marker. On 2026-11-17 the worker delivered seven queued Mailpit messages; final queue status was `email.order_created ready=0 unacked=0`, `email.dead ready=0 unacked=0`.
* PART 2 implementation and partial live verification: Soketi compose service, signed private-channel authorization and fail-open Pusher HTTP publication. Live results: admin authorization returned HTTP 200, unauthenticated authorization returned HTTP 401, and a real `pusher-js` client connected to Soketi and received `private subscription succeeded` for `private-admin-orders`.
* Frontend implementation: private subscriptions on the admin orders and customer order-detail screens, with offline indicator and existing fetch fallback.
* Static verification: backend `compileall`, Compose validation, and frontend build/lint passed in this session.
* Docker Desktop was started during this session. RabbitMQ initially failed with `.erlang.cookie: eacces` on Docker Desktop's volume permissions; it now uses the explicit `rabbitmq_data` named volume and root-owned initialisation. The worker initially raced AMQP readiness and lacked the shared RabbitMQ environment; both startup defects were fixed and verified live.
* The real Pusher client initially failed because `pusher-js` requires a `cluster` option even with an explicit WebSocket host. The frontend hook now sets `cluster: 'mt1'`; the subsequent live private subscription succeeded.
* PART 3 started: `tests/req4/` now contains four marked tests. `pytest --collect-only -q -m req4` reported `4/89 tests collected (85 deselected)`. Each currently implemented test passed when run in the tester container: topology/retry declaration, unauthenticated rejection, four channel-authorization cases, and outbox persistence.

## Next

* PART 3: worker stop/start and RabbitMQ-down tests passed in background runs (the RabbitMQ-down test: `1 passed in 114.15s`). Retry/DLQ test is currently running in `logs/req4_retry_dlq.log`. Idempotency/crash, latency, Playwright, demos and real SMTP remain **NOT VERIFIED**.
* Code preparation requested by the user: `app-inline` compose service and `test_latency_before_after.py` were added but were not executed; latency output is **NOT VERIFIED**.
* Add and execute the full Req4 integration and latency suites; collect only real result files.

## Resume commands

```powershell
docker compose --profile test up -d --build
python scripts/queue_status.py
docker compose --profile test run --rm --no-deps tester tests -m "req4 or req4_latency" -v -s
python scripts/demo_req4.py --quick
```

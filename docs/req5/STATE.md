# Requirement 5 state

- Done: nginx is the only public API door on port 8000; app and worker are scalable services without fixed names or host app ports.
- Done: shared uploads volume, instance/upstream headers, startup lock, outbox lock, and worker hostname logging.
- Next: start three replicas and record live results under `docs/req5/results/`.
- Open issues: all live measurements are NOT VERIFIED. Docker Desktop was unavailable in this session (`dockerDesktopLinuxEngine` pipe was missing), so no container/test measurement was invented. Three checks were attempted: `docker compose ps`, Windows service/process discovery, and `docker version`; all confirmed that no Linux Docker engine is installed/running.

```powershell
docker compose --profile test up -d --build --scale app=3 --scale worker=3
python scripts/load_500.py
docker compose --profile test run --rm --no-deps tester tests/req5 -m req5 -s
```

#!/usr/bin/env python3
"""Where does the CPU of ONE request go? cProfile of the ASGI app (inside the app container, real MySQL/Redis).

  docker compose run --rm --no-deps -v ./scripts:/app/scripts --entrypoint python app scripts/profile_request.py "/products?category=3&limit=20" [N]

Calls the application in-process through httpx's ASGI transport (no network), N times after a warm-up, and prints the
top functions by cumulative and by own time. Diagnostic only; nothing here is part of the benchmark numbers.
"""
import asyncio
import cProfile
import io
import os
import pstats
import sys
import time

sys.path.insert(0, '/app')
os.environ.setdefault('INVENTORY_MODE', 'grpc')
import httpx  # noqa: E402
from app.main import app  # noqa: E402

PATH = sys.argv[1] if len(sys.argv) > 1 else '/products?category=3&limit=20'
N = int(sys.argv[2]) if len(sys.argv) > 2 else 300


async def main():
    from app.integrations.inventory.gateway import configure_gateway
    configure_gateway()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url='http://t/api/v1') as c:
        r = await c.post('/auth/login', json={'email': 'customer001@loadtest.example', 'password': 'LoadTest123!'})
        h = {'Authorization': 'Bearer ' + r.json()['access_token']}
        for _ in range(20):
            await c.get(PATH, headers=h)
        t = time.perf_counter()
        pr = cProfile.Profile()
        pr.enable()
        for _ in range(N):
            resp = await c.get(PATH, headers=h)
        pr.disable()
        wall = time.perf_counter() - t
        print(f'{PATH}: status {resp.status_code}, {N} requests, {wall / N * 1000:.2f} ms per request (profiled, so inflated)')
        for sort in ('cumulative', 'tottime'):
            s = io.StringIO()
            pstats.Stats(pr, stream=s).sort_stats(sort).print_stats(22)
            print('\n'.join(line[:150] for line in s.getvalue().splitlines()[4:34]))
        # un-profiled timing
        t = time.perf_counter()
        for _ in range(N):
            await c.get(PATH, headers=h)
        print(f'un-profiled: {(time.perf_counter() - t) / N * 1000:.2f} ms per request, single client, in-process')

asyncio.run(main())

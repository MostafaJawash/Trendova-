"""Live Req 5 before/after harness. It is intentionally never run by import."""
import collections
import os
import subprocess
import threading
import time

import httpx
import pytest

pytestmark = pytest.mark.req5
PROJECT = os.getenv('COMPOSE_PROJECT_NAME', 'trendova-req3')
BASE = os.getenv('E2E_BASE_URL', 'http://nginx/api/v1').replace('/api/v1', '')
TOGGLES = [
    ('shared uploads', 'UPLOADS_SHARED'),
    ('outbox publisher coordination', 'OUTBOX_SINGLE_PUBLISHER'),
    ('startup migration lock', 'STARTUP_LOCK_ENABLED'),
    ('Redis login limiter', 'REDIS_LOGIN_LIMITER'),
    ('worker email idempotency', 'WORKER_IDEMPOTENCY'),
]


def compose_with(toggle, value):
    """Recreate only replicas; never runs down and never deletes a volume."""
    env = dict(os.environ, **{toggle: value})
    return subprocess.run(['docker', 'compose', '-p', PROJECT, 'up', '-d', '--force-recreate',
                           '--scale', 'app=3', '--scale', 'worker=3', 'app', 'worker', 'nginx'],
                          env=env, capture_output=True, text=True, timeout=180)


def request_health():
    response = httpx.get(BASE + '/health', timeout=10)
    return response.status_code, response.headers.get('X-Instance', 'MISSING')


def distribution_evidence(n=50):
    counts = collections.Counter(request_health()[1] for _ in range(n))
    print('DISTRIBUTION requests=%s instances=%s' % (n, dict(counts)))
    return counts


def test_before_after_toggle_contract_and_distribution():
    """Runs each real toggle in broken mode, then always restores fixed mode.

    Product/email race assertions belong in the specialized Req 5 tests; this
    harness is the reproducible switchboard and prints live evidence rather
    than claiming numbers in source code.
    """
    results = []
    try:
        for number, (name, toggle) in enumerate(TOGGLES, 1):
            before = compose_with(toggle, 'false')
            before_text = 'recreated=%s health=%s' % (before.returncode == 0, request_health()[0])
            after = compose_with(toggle, 'true')
            after_text = 'recreated=%s health=%s' % (after.returncode == 0, request_health()[0])
            passed = before.returncode == 0 and after.returncode == 0
            print('PROBLEM %s: %s' % (number, name))
            print('  BEFORE (%s=false): %s' % (toggle, before_text))
            print('  AFTER  (%s=true): %s' % (toggle, after_text))
            print('  RESULT %s' % ('PASS' if passed else 'FAIL'))
            results.append((name, before_text, after_text, passed))
        counts = distribution_evidence()
        assert len(counts) == 3
        assert all(row[3] for row in results)
    finally:
        for _, toggle in TOGGLES:
            compose_with(toggle, 'true')
    print('SUMMARY Problem | BEFORE | AFTER | RESULT')
    for name, before, after, passed in results:
        print('%s | %s | %s | %s' % (name, before, after, 'PASS' if passed else 'FAIL'))


def test_light_failover_evidence():
    """Stops one replica during a small request stream and restores it in finally."""
    running, errors, counts = True, [], collections.Counter()
    def load():
        while running:
            try:
                status, instance = request_health()
                counts[instance] += 1
                if status != 200: errors.append(status)
            except Exception as exc: errors.append(type(exc).__name__)
    thread = threading.Thread(target=load); thread.start()
    try:
        time.sleep(1)
        stopped = subprocess.run(['docker', 'stop', PROJECT + '-app-1'], capture_output=True, text=True, timeout=30)
        time.sleep(2)
        assert stopped.returncode == 0, stopped.stderr
    finally:
        running = False; thread.join(timeout=15)
        subprocess.run(['docker', 'start', PROJECT + '-app-1'], capture_output=True, text=True, timeout=30)
    print('FAILOVER errors=%s instances=%s' % (len(errors), dict(counts)))
    assert len(errors) <= 2

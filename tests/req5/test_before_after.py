"""Tester-side checks only. Host orchestration lives in scripts/req5_before_after.py."""
import collections
import os
from concurrent.futures import ThreadPoolExecutor
from urllib.request import urlopen

import pytest

pytestmark = pytest.mark.req5
BASE = os.getenv('E2E_BASE_URL', 'http://nginx/api/v1').replace('/api/v1', '')


def _one(_):
    with urlopen(BASE + '/health', timeout=10) as response:
        return response.status, response.headers.get('X-Instance', 'MISSING')


def test_nginx_distributes_fifty_requests():
    with ThreadPoolExecutor(max_workers=10) as pool:
        rows = list(pool.map(_one, range(50)))
    statuses = collections.Counter(status for status, _ in rows)
    instances = collections.Counter(instance for _, instance in rows)
    print('DISTRIBUTION requests=50 status=%s instances=%s' % (dict(statuses), dict(instances)))
    assert statuses == {200: 50}
    assert 'MISSING' not in instances
    assert len(instances) == 3

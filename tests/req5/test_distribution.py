import collections
import os
from concurrent.futures import ThreadPoolExecutor
import httpx
import pytest

pytestmark = pytest.mark.req5

def test_nginx_distributes_500_requests():
    base = os.getenv('E2E_BASE_URL', 'http://nginx/api/v1').replace('/api/v1', '')
    def request(_):
        response = httpx.get(base + '/health', timeout=10)
        return response.status_code, response.headers.get('X-Instance')
    with ThreadPoolExecutor(max_workers=25) as pool: rows = list(pool.map(request, range(500)))
    statuses, instances = collections.Counter(x[0] for x in rows), collections.Counter(x[1] for x in rows)
    print('REQ5 distribution requests=500 statuses=%s instances=%s' % (dict(statuses), dict(instances)))
    assert statuses == {200: 500}
    assert None not in instances
    assert len(instances) == 3, 'start with docker compose up -d --scale app=3'

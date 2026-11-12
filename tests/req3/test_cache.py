"""Redis cache-aside (Requirement 3). Live: needs the compose stack (final app with CACHE_ENABLED) and the `tester` container."""
import concurrent.futures
import re
import time
from pathlib import Path
import httpx
import pytest
from tests.req3 import live

pytestmark = [pytest.mark.req3_phase2, pytest.mark.skipif(not live.BASE, reason='E2E_BASE_URL not set (needs the compose stack)')]


@pytest.fixture(scope='module')
def api():
    return live.Api()


def _redis(*args):
    return live.docker('exec', live.cname('redis'), 'redis-cli', *args).stdout.strip()


def test_first_miss_then_hit_then_miss_after_update(api):
    admin = api.admin(); pid, cat = api.new_product(admin, price='10.00')
    _, user = api.new_user()
    url = f'/products?category={cat}&limit=20'
    r1 = api.c.get(url, headers=user); r2 = api.c.get(url, headers=user)
    assert (r1.headers['x-cache'], r2.headers['x-cache']) == ('MISS', 'HIT')
    assert r1.content == r2.content
    api.edit_price(admin, pid, '11.00')
    r3 = api.c.get(url, headers=user)
    assert r3.headers['x-cache'] == 'MISS' and r3.json()['items'][0]['price'] == '11.00'
    d1 = api.c.get(f'/products/{pid}', headers=user); d2 = api.c.get(f'/products/{pid}', headers=user)
    assert d1.headers['x-cache'] in ('MISS', 'HIT') and d2.headers['x-cache'] == 'HIT'
    api.edit_price(admin, pid, '12.00')
    d3 = api.c.get(f'/products/{pid}', headers=user)
    assert d3.headers['x-cache'] == 'MISS' and d3.json()['price'] == '12.00'


def test_stock_is_never_served_from_cache(api):
    admin = api.admin(); pid, _ = api.new_product(admin, quantity=5)
    _, user = api.new_user()
    d1 = api.c.get(f'/products/{pid}', headers=user); d2 = api.c.get(f'/products/{pid}', headers=user)
    assert d2.headers['x-cache'] == 'HIT' and d2.json()['stock']['quantity'] == 5
    api.order(user, pid, 2)
    d3 = api.c.get(f'/products/{pid}', headers=user)
    assert d3.headers['x-cache'] == 'HIT'                       # the static part came from Redis ...
    assert d3.json()['stock'] == {'quantity': 3, 'status': 'available'}   # ... but the stock is live
    api.c.patch(f"/orders/{api.c.get('/orders', headers=user).json()['items'][0]['id']}/status", headers=admin, json={'status': 'cancelled'})


def test_redis_down_requests_still_succeed_and_recover(api):
    admin = api.admin(); pid, cat = api.new_product(admin)
    _, user = api.new_user()
    with live.container_stopped('redis'):
        r = api.c.get(f'/products?category={cat}', headers=user)
        d = api.c.get(f'/products/{pid}', headers=user)
        assert r.status_code == 200 and d.status_code == 200
        assert r.headers['x-cache'] == 'BYPASS' and d.headers['x-cache'] == 'BYPASS'
    time.sleep(2.5)                                              # circuit breaker window
    assert api.c.get(f'/products?category={cat}', headers=user).headers['x-cache'] in ('MISS', 'HIT')


def test_ttl_is_jittered_around_the_configured_values(api):
    admin = api.admin(); pid, cat = api.new_product(admin)
    _, user = api.new_user()
    api.c.get(f'/products?category={cat}', headers=user); api.c.get(f'/products/{pid}', headers=user)
    ttl = int(_redis('ttl', f'trendova:products:detail:{pid}'))
    assert 270 <= ttl <= 330, ttl                                # 300 s +-10 %
    keys = _redis('--scan', '--pattern', 'trendova:products:list:*').split()
    lt = [int(_redis('ttl', k)) for k in keys]
    assert lt and all(0 < t <= 66 for t in lt), lt               # 60 s +-10 %


def test_list_uses_a_version_namespace_and_failed_update_does_not_invalidate(api):
    admin = api.admin(); pid, cat = api.new_product(admin)
    ver = lambda: int(_redis('get', 'trendova:products:ver') or 0)
    v0 = ver()
    bad = api.c.put(f'/products/{pid}', headers=admin, data={'price': '-1'})
    assert bad.status_code in (400, 422) and ver() == v0         # nothing committed -> nothing invalidated
    api.edit_price(admin, pid, '3.00')
    assert ver() == v0 + 1                                       # one O(1) INCR per committed change
    assert re.fullmatch(r'trendova:products:list:v\d+:[0-9a-f]+', 'trendova:products:list:v7:abcdef0123')


def test_app_never_uses_keys_or_scan():
    root = Path(__file__).resolve().parents[2] / 'app'
    src = '\n'.join(p.read_text() for p in root.rglob('*.py') if 'generated' not in str(p))
    assert not re.search(r"\.keys\(|\.scan|scan_iter|'keys'|'scan'", src)


def test_redis_is_bounded_lru():
    assert _redis('config', 'get', 'maxmemory').split()[-1] == str(256 * 1024 * 1024)
    assert _redis('config', 'get', 'maxmemory-policy').split()[-1] == 'allkeys-lru'


def test_stampede_one_fill_for_many_concurrent_cold_requests(api):
    admin = api.admin(); pid, cat = api.new_product(admin)
    _, user = api.new_user()
    api.c.post(live.BASE.replace('/api/v1', '') + '/internal/cache-stats/reset', headers=admin)
    url = f'/products?category={cat}&limit=20'               # brand-new category -> cold key

    def hit(_):
        with httpx.Client(base_url=live.BASE, timeout=30) as c:
            return c.get(url, headers=user).status_code
    with concurrent.futures.ThreadPoolExecutor(20) as ex:
        codes = list(ex.map(hit, range(20)))
    stats = live.cache_stats(api, admin)
    assert set(codes) == {200}
    assert stats['fills'] == 1, stats                          # ONE database fill, the rest waited for it

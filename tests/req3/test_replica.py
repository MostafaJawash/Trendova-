"""MySQL read replica + read-your-writes (Requirement 3). Live: needs the compose stack and the `tester` container.

The replica lag is made deterministic with CHANGE REPLICATION SOURCE TO SOURCE_DELAY=3 (always restored to 0 afterwards).
"""
import time
import pytest
from tests.req3 import live

pytestmark = [pytest.mark.req3_phase2, pytest.mark.skipif(not live.BASE, reason='E2E_BASE_URL not set (needs the compose stack)')]
RYW = 5   # RYW_WINDOW_SECONDS default of the running app


@pytest.fixture(scope='module')
def api():
    return live.Api()


def _select_count(host):
    out = live.mysql("SHOW GLOBAL STATUS LIKE 'Com_select'", host=host)
    return int(out.split()[-1])


def test_replication_is_running_and_replica_is_read_only():
    st = live.replica_status()
    assert st['Replica_IO_Running'] == 'Yes' and st['Replica_SQL_Running'] == 'Yes', st
    assert st['Seconds_Behind_Source'].isdigit()
    assert live.mysql('SELECT @@read_only, @@super_read_only', host='db-replica').split() == ['1', '1']


def test_writes_never_reach_the_replica_directly(api):
    """A direct write on the replica is rejected, and the replica never produced a transaction of its own:
    every GTID it has executed comes from the primary's UUID."""
    out = live.mysql("CREATE TABLE req3_should_fail (id INT)", host='db-replica')
    assert 'read-only' in out.lower(), out
    own_uuid = live.mysql('SELECT @@server_uuid', host='db-replica').strip()
    gtids = live.mysql('SELECT @@gtid_executed', host='db-replica').replace('\n', '')
    assert own_uuid not in gtids, 'the replica executed a local transaction'


def test_app_reads_go_to_the_replica_when_no_marker(api):
    """my_orders by a user with no recent write is answered by the replica (its Com_select counter moves, the user's own
    reads of a freshly written state go to the primary)."""
    _, user = api.new_user()
    time.sleep(0.2)
    before = _select_count('db-replica')
    for _ in range(3):
        assert api.c.get('/orders', headers=user).status_code == 200
    assert _select_count('db-replica') >= before + 3


def test_replica_down_is_still_served_from_the_primary(api):
    _, user = api.new_user()
    with live.container_stopped('db-replica'):
        for _ in range(3):   # first request opens the circuit breaker, the next ones skip the dead replica
            r = api.c.get('/orders', headers=user)
            assert r.status_code == 200, r.text
        assert api.c.get('/products?search=lamp&limit=5', headers=user).status_code == 200
        assert api.c.get('/dashboard/stats', headers=api.admin()).status_code == 200
    assert live.wait_replica_caught_up(), 'replica did not resume replication'


def test_redis_down_is_still_served_from_the_primary(api):
    _, user = api.new_user()
    with live.container_stopped('redis'):
        for _ in range(3):
            r = api.c.get('/orders', headers=user)
            assert r.status_code == 200, r.text
        assert api.c.get('/products?limit=5', headers=user).status_code == 200


def test_read_your_writes_under_replica_lag(api):
    admin = api.admin()
    pid, _ = api.new_product(admin, quantity=10)
    uid, user = api.new_user()
    time.sleep(RYW + 1)                         # admin / user markers from the setup writes expire
    with live.source_delay(3):
        order = api.order(user, pid)
        # the author sees the new order immediately (marker -> primary) ...
        mine = api.c.get('/orders', headers=user).json()
        assert [o['id'] for o in mine['items']] == [order['id']]
        # ... while a reader without a marker (the admin's list, replica) does NOT see it yet: the lag is real
        stale = api.c.get(f'/orders?user_id={uid}', headers=admin).json()
        assert stale['total'] == 0, 'replica should still be lagging (SOURCE_DELAY=3)'
        # once the delay has passed the replica catches up
        time.sleep(4)
        assert api.c.get(f'/orders?user_id={uid}', headers=admin).json()['total'] == 1


def _hammer_orders(base, headers, n=40):
    """n concurrent 'my orders' requests (more than the 15 pooled primary connections)."""
    import concurrent.futures
    import httpx

    def one(_):
        with httpx.Client(base_url=base, timeout=40) as c:
            return c.get('/orders?limit=10', headers=headers).status_code
    t = time.time()
    with concurrent.futures.ThreadPoolExecutor(n) as ex:
        codes = list(ex.map(one, range(n)))
    return codes, time.time() - t


def test_no_connection_pool_exhaustion_when_the_replica_is_off():
    """Regression for a bug the final benchmark exposed: with USE_READ_REPLICA=false `read_db` opened a SECOND primary session
    while the auth session was still held, so >15 concurrent requests deadlocked on the pool until pool_timeout (30 s).
    Runs against the flags-off instance `app-v1` (compose profile `ab`); skipped when it is not running."""
    import os
    import httpx
    base = os.getenv('E2E_V1_URL', 'http://app-v1:8000/api/v1')
    try:
        r = httpx.post(base + '/auth/login', json={'email': 'customer001@loadtest.example', 'password': 'LoadTest123!'}, timeout=5)
    except Exception:
        pytest.skip('app-v1 (flags off) is not running: docker compose --profile ab up -d app-v1')
    codes, took = _hammer_orders(base, {'Authorization': 'Bearer ' + r.json()['access_token']})
    assert set(codes) == {200} and took < 25, (set(codes), took)


def test_no_connection_pool_exhaustion_when_the_replica_is_down(api):
    """Same shape on the final app: the replica is stopped, every read falls back to the primary session of the request."""
    _, user = api.new_user()
    with live.container_stopped('db-replica'):
        api.c.get('/orders', headers=user)        # opens the circuit breaker
        codes, took = _hammer_orders(live.BASE, user)
        assert set(codes) == {200} and took < 25, (set(codes), took)
    assert live.wait_replica_caught_up()

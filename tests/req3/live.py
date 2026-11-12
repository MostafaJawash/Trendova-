"""Helpers for the live Requirement 3 tests (they talk to the running compose stack).

They run inside the `tester` container (docker compose --profile test run tester ...) which has the docker CLI and the
docker socket, so a test can stop Redis / the replica / the inventory service and ALWAYS start it again in `finally`.

Hygiene: throw-away data is named `req3_test_<random>`, is removed by scripts/req3_cleanup.py at the end of a run and
never enters benchmark numbers or seed counts.
"""
import contextlib
import os
import subprocess
import time
import uuid
import httpx

BASE = os.getenv('E2E_BASE_URL')                         # e.g. http://app:8000/api/v1
PROJECT = os.getenv('COMPOSE_PROJECT_NAME', 'trendova-req3')
ADMIN_EMAIL = os.getenv('E2E_ADMIN_EMAIL', 'admin@example.com')
ADMIN_PASSWORD = os.getenv('E2E_ADMIN_PASSWORD', 'ChangeMe123!')
DB_NAME = os.getenv('DATABASE_NAME', 'ecommerce')


def tag():
    return 'req3_test_' + uuid.uuid4().hex[:8]


def cname(service):
    return f'{PROJECT}-{service}-1'


def docker(*args, check=True, input=None, timeout=120):
    return subprocess.run(['docker', *args], capture_output=True, text=True, check=check, input=input, timeout=timeout)


def mysql(sql, host='db'):
    """Run SQL as root inside the primary (`db`) or the replica (`db-replica`); returns stdout."""
    r = docker('exec', '-i', cname(host), 'sh', '-c', f'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" {DB_NAME} -N -B 2>&1 | grep -v "Using a password"', input=sql, check=False)
    return r.stdout.strip()


def replica_status():
    out = docker('exec', cname('db-replica'), 'sh', '-c', 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "SHOW REPLICA STATUS\\G" 2>/dev/null', check=False).stdout
    return {k.strip(): v.strip() for k, _, v in (line.partition(':') for line in out.splitlines()) if _}


def wait_replica_caught_up(timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        st = replica_status()
        if st.get('Replica_IO_Running') == 'Yes' and st.get('Replica_SQL_Running') == 'Yes' and st.get('Seconds_Behind_Source') == '0' and 'read all relay log' in st.get('Replica_SQL_Running_State', ''):
            return True
        time.sleep(1)
    return False


def wait_running(service, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        r = docker('inspect', '-f', '{{.State.Health.Status}}', cname(service), check=False)
        if r.stdout.strip() in ('healthy', '') and docker('inspect', '-f', '{{.State.Running}}', cname(service), check=False).stdout.strip() == 'true':
            return True
        time.sleep(1)
    return False


@contextlib.contextmanager
def container_stopped(service):
    """Stop a compose service for the duration of the block; it is ALWAYS started again."""
    docker('stop', '-t', '2', cname(service))
    try:
        yield
    finally:
        docker('start', cname(service))
        wait_running(service)


@contextlib.contextmanager
def source_delay(seconds):
    """Deterministic replica lag: SOURCE_DELAY=<seconds>; restored to 0 afterwards (and the replica is waited for)."""
    def apply(n):
        mysql(f'STOP REPLICA SQL_THREAD; CHANGE REPLICATION SOURCE TO SOURCE_DELAY={n}; START REPLICA SQL_THREAD;', host='db-replica')
    apply(seconds)
    try:
        yield
    finally:
        apply(0)
        wait_replica_caught_up()


class Api:
    def __init__(self):
        self.c = httpx.Client(base_url=BASE, timeout=30)

    def login(self, email, password):
        r = self.c.post('/auth/login', json={'email': email, 'password': password})
        assert r.status_code == 200, r.text
        return {'Authorization': 'Bearer ' + r.json()['access_token']}

    def admin(self):
        return self.login(ADMIN_EMAIL, ADMIN_PASSWORD)

    def new_user(self):
        email = f'{tag()}@example.com'
        r = self.c.post('/auth/register', json={'email': email, 'name': 'req3 test', 'password': 'password123'})
        assert r.status_code == 201, r.text
        return r.json()['id'], self.login(email, 'password123')

    def new_product(self, admin, price='9.99', quantity=5, category_id=None):
        if category_id is None:
            category_id = self.c.post('/categories', headers=admin, json={'name': tag(), 'description': 'req3 test'}).json()['id']
        r = self.c.post('/products', headers=admin, data={'name': tag(), 'description': 'req3 test product', 'price': price, 'category_id': category_id, 'initial_quantity': quantity})
        assert r.status_code == 201, r.text
        return r.json()['id'], category_id

    def edit_price(self, admin, pid, price):
        r = self.c.put(f'/products/{pid}', headers=admin, data={'price': price})
        assert r.status_code == 200, r.text
        return r

    def order(self, headers, pid, quantity=1):
        r = self.c.post('/orders', headers=headers, json={'items': [{'product_id': pid, 'quantity': quantity}]})
        assert r.status_code == 201, r.text
        return r.json()


def cache_stats(api, admin):
    r = api.c.get(BASE.replace('/api/v1', '') + '/internal/cache-stats', headers=admin)
    assert r.status_code == 200, r.text
    return r.json()

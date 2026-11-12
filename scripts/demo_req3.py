#!/usr/bin/env python3
"""Requirement 3 - live BEFORE / AFTER demo for the oral discussion (terminal only, ASCII only, stdlib only).

  py scripts/demo_req3.py                 # full demo
  py scripts/demo_req3.py --quick         # shorter runs
  py scripts/demo_req3.py --pause         # wait for Enter between steps
  py scripts/demo_req3.py --step 6        # one step only
  py scripts/demo_req3.py --duration 30   # seconds of load per variant (default 20, quick 10)
  py scripts/demo_req3.py --from-results  # print the SAVED results of the last live run (no Docker needed)
  py scripts/demo_req3.py --no-color

Every number comes from a live measurement of this run (or, with --from-results, from the saved JSON files).
Nothing that cannot be measured is printed as a number: it is shown as NOT MEASURED and counts as not passed.

BEFORE = baseline image built from the last commit before any Req 3 change (git archive, port 8010) with the ORIGINAL indexes.
AFTER  = the final service (port 8000): composite indexes, query fixes, GetStockBatch, read replica, Redis cache, ETag.
Everything the demo changes (indexes, replication delay, stopped containers) is restored in a `finally` block.
Test data is named `req3_demo_*` and removed at the end. Seeded data and Docker volumes are never touched.
"""
import argparse
import concurrent.futures
import ctypes
import hashlib
import json
import os
import re
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _stack as st  # noqa: E402
import ab_runner as abr  # noqa: E402

ROOT = st.ROOT
RESULTS = st.RESULTS
SAVED = RESULTS / 'demo_last.json'
ADMIN = (os.getenv('DEMO_ADMIN_EMAIL', 'admin@example.com'), os.getenv('DEMO_ADMIN_PASSWORD', 'ChangeMe123!'))
CUSTOMER = ('customer001@loadtest.example', 'LoadTest123!')
PORT_AFTER, PORT_BEFORE, PORT_V1, PORT_DIAG = 8000, 8010, 8011, 8030
NOT_MEASURED = 'NOT MEASURED'
TOTAL_STEPS = 9


# ----------------------------------------------------------------------------- output helpers
class Console:
    color = True

    def paint(self, code, text):
        return f'\033[{code}m{text}\033[0m' if self.color else text

    def p(self, text=''):
        try:
            print(text, flush=True)
        except UnicodeEncodeError:
            print(text.encode('ascii', 'replace').decode('ascii'), flush=True)

    def tag(self, ok):
        if ok is None:
            return self.paint('33', 'NOT MEASURED')
        return self.paint('32;1', 'PASS') if ok else self.paint('31;1', 'FAIL')


con = Console()


def enable_color(disable):
    if disable or not sys.stdout.isatty():
        con.color = False
        return
    if os.name == 'nt':
        try:
            k = ctypes.windll.kernel32
            h = k.GetStdHandle(-11)
            mode = ctypes.c_ulong()
            k.GetConsoleMode(h, ctypes.byref(mode))
            k.SetConsoleMode(h, mode.value | 0x0004)   # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except Exception:
            con.color = False


def fmt(x, nd=1):
    return NOT_MEASURED if x is None else f'{x:.{nd}f}'


def ratio(before, after):
    return None if not before or not after else before / after


def rtxt(r):
    return NOT_MEASURED if r is None else f'{r:.2f}x'


class Step:
    """One step = title, what is measured, BEFORE / AFTER lines, RESULT line, evidence line."""

    def __init__(self, n, title, what):
        self.n, self.title, self.what = n, title, what
        self.ok = None
        self.facts = {}
        self.t0 = time.time()
        con.p()
        con.p(con.paint('36;1', f'[STEP {n}/{TOTAL_STEPS}] {title}'))
        con.p(f'  measures: {what}')

    def line(self, label, text):
        col = {'BEFORE': '33', 'AFTER': '32'}.get(label.strip(), '0')
        con.p(f'  {con.paint(col, f"{label:<7}")} {text}')

    def result(self, ok, msg, evidence, info=False):
        self.ok = ok
        con.p(f'  RESULT  {con.paint("36;1", "INFO") if info else con.tag(ok)}  ({msg})')
        con.p(f'  evidence: {evidence}')
        self.facts['seconds'] = round(time.time() - self.t0, 1)
        return self


# ----------------------------------------------------------------------------- HTTP helpers
class Resp:
    def __init__(self, status, headers, body, ms, error=None):
        self.status, self.headers, self.body, self.ms, self.error = status, headers, body, ms, error

    def json(self):
        return json.loads(self.body or b'null')


def call(port, method, path, token=None, headers=None, form=None, js=None, timeout=60):
    url = f'http://localhost:{port}/api/v1{path}'
    h = dict(headers or {})
    data = None
    if token:
        h['Authorization'] = 'Bearer ' + token
    if js is not None:
        data, h['Content-Type'] = json.dumps(js).encode(), 'application/json'
    elif form is not None:
        data, h['Content-Type'] = urllib.parse.urlencode(form).encode(), 'application/x-www-form-urlencoded'
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    t = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body, status, hd = r.read(), r.status, {k.lower(): v for k, v in r.getheaders()}
    except urllib.error.HTTPError as e:
        body, status, hd = e.read(), e.code, {k.lower(): v for k, v in e.headers.items()}
    except Exception as e:  # connection refused, timeout ...
        return Resp(0, {}, b'', (time.perf_counter() - t) * 1000, error=str(e))
    return Resp(status, hd, body, (time.perf_counter() - t) * 1000)


def login(port, email, password):
    r = call(port, 'POST', '/auth/login', js={'email': email, 'password': password})
    return r.json()['access_token'] if r.status == 200 else None


def docker(*args, timeout=120):
    return subprocess.run(['docker', *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout)


def cname(service):
    return f'trendova-req3-{service}-1'


def replica_sql(sql):
    r = st.compose('exec', '-T', 'db-replica', 'sh', '-c', 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" ecommerce -e "$0" 2>&1 | grep -v "Using a password"', sql)
    return (r.stdout + r.stderr).strip()


def com_select():
    out = st.mysql("SHOW GLOBAL STATUS LIKE 'Com_select'")
    return int(out.split()[-1]) if out.split() else None


def redis_cli(*args):
    return docker('exec', cname('redis'), 'redis-cli', *args).stdout.strip()


def wait_container(service, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        r = docker('inspect', '-f', '{{.State.Running}} {{if .State.Health}}{{.State.Health.Status}}{{end}}', cname(service))
        if r.stdout.strip().startswith('true') and 'unhealthy' not in r.stdout and 'starting' not in r.stdout:
            return True
        time.sleep(1)
    return False


# ----------------------------------------------------------------------------- demo context
class Demo:
    def __init__(self, args):
        self.args = args
        self.quick = args.quick
        self.duration = args.duration or (10 if args.quick else 20)
        self.tag = 'req3_demo_' + uuid.uuid4().hex[:6]
        self.admin = None
        self.cust = None
        self.cust_id = None
        self.cat = None
        self.pid = None
        self.last_admin_write = 0.0
        self.steps = {}
        self.facts = {}
        self.fixtures_ready = False

    # --- fixtures (lazy) -------------------------------------------------------
    def admin_write(self):
        self.last_admin_write = time.time()

    def fixtures(self):
        if self.fixtures_ready:
            return
        self.admin = login(PORT_AFTER, *ADMIN)
        c = call(PORT_AFTER, 'POST', '/categories', self.admin, js={'name': self.tag, 'description': 'req3 demo'})
        self.cat = c.json()['id']
        for i in range(25):   # a realistic page of 20 items plus a few more
            r = call(PORT_AFTER, 'POST', '/products', self.admin, form={'name': f'{self.tag}_{i:02d}', 'description': 'demo product', 'price': '10.00',
                                                                    'category_id': str(self.cat), 'initial_quantity': '1000000' if i == 0 else '100'})
            if i == 0:
                self.pid = r.json()['id']
        email = f'{self.tag}_u@example.com'
        reg = call(PORT_AFTER, 'POST', '/auth/register', js={'email': email, 'name': 'req3 demo', 'password': 'password123'})
        self.cust_id = reg.json()['id']
        self.cust = login(PORT_AFTER, email, 'password123')
        self.admin_write()
        self.fixtures_ready = True

    def wait_no_marker(self):
        """The admin's read-your-writes marker lives RYW_WINDOW_SECONDS (5 s): wait until it is gone."""
        left = 6.5 - (time.time() - self.last_admin_write)
        if left > 0:
            time.sleep(left)


# ----------------------------------------------------------------------------- steps
def step0(d):
    s = Step(0, 'Preflight', 'health of every service, active flags, row counts')
    s.n = 0
    ps = {}
    for line in st.compose('ps', '--format', '{{.Service}}|{{.Status}}').stdout.splitlines():
        svc, _, status = line.partition('|')
        ps[svc] = status
    need = ['app', 'db', 'db-replica', 'redis', 'inventory-service', 'inventory-db']
    healthy = {k: ('Up' in ps.get(k, '') and 'unhealthy' not in ps.get(k, '') and 'starting' not in ps.get(k, '')) for k in need}
    s.line('AFTER', 'services: ' + ', '.join(f'{k}={"up" if v else "DOWN"}' for k, v in healthy.items()))
    env = docker('inspect', cname('app'), '--format', '{{range .Config.Env}}{{println .}}{{end}}').stdout
    flags = {k: (re.search(rf'^{k}=(.*)$', env, re.M) or [None, '?'])[1] for k in ('USE_READ_REPLICA', 'CACHE_ENABLED', 'ETAG_ENABLED')}
    s.line('AFTER', 'flags in effect: ' + ', '.join(f'{k}={v}' for k, v in flags.items()))
    rep = st.replica_status()
    s.line('AFTER', f"replication: IO={rep.get('Replica_IO_Running', '?')} SQL={rep.get('Replica_SQL_Running', '?')} lag={rep.get('Seconds_Behind_Source', '?')}s")
    counts = st.row_counts()
    inv = st.inventory_rows()
    s.line('AFTER', 'rows: ' + ', '.join(f'{k}={v:,}' for k, v in counts.items()) + f', inventory={inv:,}')
    # A/B containers (baseline image + V1 + diagnostics instance)
    if subprocess.run(['docker', 'image', 'inspect', 'trendova-req3-baseline'], cwd=ROOT, capture_output=True).returncode != 0:
        con.p('  building the baseline image from the last pre-Req-3 commit (one time, about 1-2 min) ...')
        subprocess.run([sys.executable, 'scripts/ab_build.py', 'baseline'], cwd=ROOT, check=True)
    st.compose('--profile', 'ab', 'up', '-d', '--no-deps', 'app-v0', 'app-v1', 'app-diag')
    up = all(st.wait_url(f'http://localhost:{p}/health', 90) for p in (PORT_BEFORE, PORT_V1, PORT_DIAG, PORT_AFTER))
    s.line('AFTER', f'A/B containers: baseline :{PORT_BEFORE}, V1 :{PORT_V1}, diagnostics :{PORT_DIAG} -> ' + ('healthy' if up else 'NOT HEALTHY'))
    big = counts.get('products', 0) >= 20000 and counts.get('orders', 0) >= 300000 and counts.get('order_items', 0) >= 800000
    ok = all(healthy.values()) and up and rep.get('Replica_IO_Running') == 'Yes' and rep.get('Replica_SQL_Running') == 'Yes' and big
    d.facts.update(counts=counts, inventory_rows=inv, flags=flags)
    return s.result(ok, 'all services healthy, replication running, realistic data volume' if ok else 'something is down or the dataset is small', 'docker compose ps / SHOW REPLICA STATUS / SELECT COUNT(*)')


EXPLAIN_PAIRS = [   # (title, BEFORE scenario, AFTER scenario)
    ('category page (limit 20)', 'list: category page 1 (limit 20)', 'list: category page 1 (limit 20)'),
    ('newest page (limit 20)', 'list: newest page 1', 'list: newest page 1'),
    ('deep page 900 (offset) -> keyset cursor', 'list: deep page 900 (offset 17,980)', 'list: keyset deep page (cursor)'),
    ('search "wireless"', 'search: "wireless" (limit 20)', 'search: "wireless" (limit 20)'),
    ('my orders, hottest user', 'my_orders: hottest user page 1 (limit 10)', 'my_orders: hottest user page 1 (limit 10)'),
]


def page_plan(sc):
    for p in sc['plans']:
        low = p['sql'].lower()
        if 'count(' not in low and 'from favorites' not in low and 'order_items.order_id' not in low:
            return p
    return None


def run_explain(service, label):
    vol = [f'{ROOT.as_posix()}/scripts:/app/scripts', f'{ROOT.as_posix()}/loadtest/results:/app/loadtest/results']
    cmd = ['--profile', 'ab', 'run', '--rm', '--no-deps', '-v', vol[0], '-v', vol[1], '-e', f'LABEL={label}', '-e', 'SKIP_DASHBOARD=1', '--entrypoint', 'python', service, 'scripts/explain_hot.py']
    st.compose(*cmd)
    p = RESULTS / f'explain_{label}.json'
    return json.loads(p.read_text())['scenarios'] if p.exists() else None


def step1(d):
    s = Step(1, 'Slow queries: EXPLAIN ANALYZE before vs after', 'the SQL the real application emits for the hot endpoints: access, key, rows examined, time')
    if d.quick:
        con.p('  (--quick: BEFORE = baseline code with the final indexes present; the full demo also drops the new indexes first)')
    else:
        abr.set_indexes(False)
    before = run_explain('app-v0', 'demo_before')
    if not d.quick:
        abr.set_indexes(True)
    after = run_explain('app', 'demo_after')
    if not before or not after:
        return s.result(None, 'could not run EXPLAIN in the containers', 'scripts/explain_hot.py')
    ratios, bad = [], []
    for title, b_name, a_name in EXPLAIN_PAIRS:
        b, a = page_plan(before.get(b_name, {'plans': []})), page_plan(after.get(a_name, {'plans': []}))
        if not b or not a:
            continue
        desc = lambda p: f"{p['time_ms']:.3f} ms, rows examined {p['max_rows_examined']}, {'FULL SCAN' if p['full_scan'] else 'index'}, {'filesort' if p['filesort'] else 'no sort'}"
        s.line('BEFORE', f'{title:<40} {desc(b)}')
        s.line('AFTER', f"{'':<40} {desc(a)}   key: {(a['access'] or ['-'])[0][:60]}")
        r = ratio(b['time_ms'], a['time_ms'])
        ratios.append(r)
        con.p(f'          speed-up {rtxt(r)}')
        if a['full_scan'] or a['filesort']:
            bad.append(title)
    big = [r for r in ratios if r and r >= 2]
    d.facts['explain_ratios'] = [round(r, 2) for r in ratios if r]
    ok = len(big) >= 3 and not bad
    return s.result(ok, f'{len(big)} of {len(ratios)} hot queries at least 2x faster; min {rtxt(min(ratios))}, max {rtxt(max(ratios))}' if ratios else NOT_MEASURED,
                    'loadtest/results/explain_demo_before.json, explain_demo_after.json (scripts/explain_hot.py)')


def selects_of(port, path, token):
    call(port, 'GET', path, token)           # warm connection / pool
    a = com_select(); b = com_select()
    call(port, 'GET', path, token)
    c = com_select()
    return None if None in (a, b, c) else c - b - (b - a)


def step2(d):
    s = Step(2, 'N+1: statements per request and gRPC calls per request', 'SELECTs reaching MySQL per request at limit 10/50/100 (before: baseline app, after: new app) and warehouse calls per list-with-stock request')
    tb, ta = login(PORT_BEFORE, *CUSTOMER), login(PORT_V1, *CUSTOMER)
    ok_all = True
    lims = (10, 100) if d.quick else (10, 50, 100)
    for ep, tmpl in (('product list', '/products?limit={}'), ('my orders', '/orders?limit={}')):
        bef = [selects_of(PORT_BEFORE, tmpl.format(n), tb) for n in lims]
        aft = [selects_of(PORT_V1, tmpl.format(n), ta) for n in lims]
        s.line('BEFORE', f'{ep:<13} limit {'/'.join(map(str, lims))} -> SELECTs {bef}')
        s.line('AFTER', f'{ep:<13} limit {'/'.join(map(str, lims))} -> SELECTs {aft}  ({"constant" if len(set(aft)) == 1 else "GROWS"})')
        ok_all &= None not in aft and len(set(aft)) == 1
        d.facts[f'selects_{ep}'] = {'before': bef, 'after': aft}
    con.p('          (the old code had no per-row ORM N+1 either: the counts are constant before AND after; the extra statements are the')
    con.p('           favorites IN-query and the order_items selectin-query that replaced joins inside a LIMIT subquery)')
    td = login(PORT_DIAG, *CUSTOMER)
    naive, batch = [], []
    for n in lims:
        rn = call(PORT_DIAG, 'GET', f'/products?limit={n}&include_stock=true&stock_mode=naive', td)
        rb = call(PORT_DIAG, 'GET', f'/products?limit={n}&include_stock=true&stock_mode=batch', td)
        naive.append(int(rn.headers.get('x-inventory-rpc-calls', -1)) if rn.status == 200 else None)
        batch.append(int(rb.headers.get('x-inventory-rpc-calls', -1)) if rb.status == 200 else None)
    s.line('BEFORE', f'list with stock, per-item calls, limit {'/'.join(map(str, lims))} -> gRPC calls {naive}')
    s.line('AFTER', f'list with stock, GetStockBatch,   limit {'/'.join(map(str, lims))} -> gRPC calls {batch}')
    grpc_ok = naive == list(lims) and batch == [1] * len(lims)
    d.facts['grpc_calls'] = {'naive': naive, 'batch': batch}
    return s.result(ok_all and grpc_ok, 'statement counts constant in page size; warehouse calls N -> 1' if ok_all and grpc_ok else 'a count is not as expected',
                    'SHOW GLOBAL STATUS Com_select delta; X-Inventory-Rpc-Calls header of the diagnostics instance (DB_QUERY_COUNT=1)')


class Hammer:
    """Closed-loop order creation by throw-away users on the throw-away product (all rows are removed at the end)."""

    def __init__(self, d, users=4):
        self.d = d
        self.tokens = []
        for i in range(users):
            email = f'{d.tag}_w{i}@example.com'
            call(PORT_AFTER, 'POST', '/auth/register', js={'email': email, 'name': 'req3 demo', 'password': 'password123'})
            self.tokens.append(login(PORT_AFTER, email, 'password123'))

    def run(self, seconds):
        lat, stop = [], time.time() + seconds
        lock = threading.Lock()

        def work(tok):
            while time.time() < stop:
                r = call(PORT_V1, 'POST', '/orders', tok, js={'items': [{'product_id': self.d.pid, 'quantity': 1}]})
                if r.status == 201:
                    with lock:
                        lat.append(r.ms)
        with concurrent.futures.ThreadPoolExecutor(len(self.tokens)) as ex:
            list(ex.map(work, self.tokens))
        return {'orders_per_s': len(lat) / seconds, 'p50_ms': statistics.median(lat) if lat else None, 'n': len(lat)}


def step3(d):
    s = Step(3, 'What slows an index down? create_order with and without the new orders index', 'orders/s of 4 concurrent buyers, interleaved A B B A (only the orders(user_id, created_at, id) index is toggled)')
    if d.quick:
        return s.result(None, 'skipped in --quick (run: py scripts/demo_req3.py --step 3); saved k6 result: optimization_log entry 3', 'scripts/demo_req3.py --step 3', info=True)
    d.fixtures()
    h = Hammer(d)
    secs = 5
    seq = ['A', 'B', 'B', 'A']
    res = {'A': [], 'B': []}
    try:
        for cond in seq:
            names = abr.index_names()
            if cond == 'A' and 'idx_orders_user_created' in names:
                st.mysql('DROP INDEX idx_orders_user_created ON orders')
            if cond == 'B' and 'idx_orders_user_created' not in names:
                st.mysql('CREATE INDEX idx_orders_user_created ON orders (user_id, created_at, id)')
            abr.wait_replica_sync()
            r = h.run(secs)
            res[cond].append(r)
            con.p(f'          run {cond}: {r["orders_per_s"]:.1f} orders/s, p50 {fmt(r["p50_ms"])} ms ({r["n"]} orders)')
    finally:
        if 'idx_orders_user_created' not in abr.index_names():
            st.mysql('CREATE INDEX idx_orders_user_created ON orders (user_id, created_at, id)')
    a = statistics.mean(x['orders_per_s'] for x in res['A'])
    b = statistics.mean(x['orders_per_s'] for x in res['B'])
    spread = max(abs(res[c][0]['orders_per_s'] - res[c][1]['orders_per_s']) for c in 'AB')
    s.line('BEFORE', f'without the new index: {a:.1f} orders/s (runs {[round(x["orders_per_s"], 1) for x in res["A"]]})')
    s.line('AFTER', f'with the new index:    {b:.1f} orders/s (runs {[round(x["orders_per_s"], 1) for x in res["B"]]})')
    diff = (a - b) / a * 100 if a else None
    verdict = 'within noise: the extra B-tree insert is not measurable here' if diff is not None and abs(a - b) <= spread else f'write throughput changed by {diff:+.1f} %'
    d.facts['index_write_cost'] = {'without': round(a, 2), 'with': round(b, 2), 'noise_spread': round(spread, 2)}
    con.p('          every INSERT also inserts into every secondary index: that (plus disk/memory) is what slows an index down')
    return s.result(None if not a else True, verdict, 'live interleaved run through POST /orders; see optimization_log entry 3 for the k6 version', info=True)


def step4(d):
    s = Step(4, 'Read replica and read-your-writes', 'replication state, read-only replica, and a user reading their own write while the replica lags by 3 s')
    d.fixtures()
    rep = st.replica_status()
    s.line('AFTER', f"replica: IO={rep.get('Replica_IO_Running')} SQL={rep.get('Replica_SQL_Running')} lag={rep.get('Seconds_Behind_Source')}s, read_only/super_read_only = {st.mysql('SELECT @@read_only, @@super_read_only', host='db-replica').split()}")
    err = replica_sql('CREATE TABLE req3_demo_nope (id INT)')
    rejected = 'read-only' in err.lower()
    s.line('AFTER', 'write on the replica -> ' + (err.splitlines()[-1][:90] if err else '(no output)'))
    d.wait_no_marker()
    own, other = None, None
    delay_set = False
    try:
        replica_sql('STOP REPLICA SQL_THREAD; CHANGE REPLICATION SOURCE TO SOURCE_DELAY=3; START REPLICA SQL_THREAD;')
        delay_set = True
        o = call(PORT_AFTER, 'POST', '/orders', d.cust, js={'items': [{'product_id': d.pid, 'quantity': 1}]}).json()
        mine = call(PORT_AFTER, 'GET', '/orders?limit=5', d.cust).json()
        own = o['id'] in [x['id'] for x in mine['items']]
        stale = call(PORT_AFTER, 'GET', f'/orders?user_id={d.cust_id}', d.admin).json()
        other = o['id'] in [x['id'] for x in stale['items']]
        s.line('BEFORE', f'reader WITHOUT the marker (admin list, replica) right after the write, SOURCE_DELAY=3 -> sees the new order: {other}  (False proves the lag is real)')
        s.line('AFTER', f'the author reads right after the write (marker -> primary)                         -> sees the new order: {own}')
        time.sleep(4.5)
        later = call(PORT_AFTER, 'GET', f'/orders?user_id={d.cust_id}', d.admin).json()
        caught_up = o['id'] in [x['id'] for x in later['items']]
        s.line('AFTER', f'the other reader 4.5 s later (replica caught up)                                  -> sees the new order: {caught_up}')
    finally:
        if delay_set:
            replica_sql('STOP REPLICA SQL_THREAD; CHANGE REPLICATION SOURCE TO SOURCE_DELAY=0; START REPLICA SQL_THREAD;')
            abr.wait_replica_sync()
    ok = rejected and own is True and other is False and caught_up
    d.facts['ryw'] = {'author_sees': own, 'other_sees_during_lag': other, 'other_sees_after': caught_up, 'replica_rejects_writes': rejected}
    return s.result(ok, 'replica is read-only; the author sees the write at once, a marker-less reader only after the lag' if ok else 'unexpected visibility', 'SHOW REPLICA STATUS, CHANGE REPLICATION SOURCE TO SOURCE_DELAY=3 (restored to 0)')


def step5(d):
    s = Step(5, 'Redis cache: MISS/HIT, TTL, invalidation, live stock, fail-open, stampede', 'X-Cache header and latency, key TTL, price edit visible at once, stock never cached, Redis stopped, 20 concurrent cold requests')
    d.fixtures()
    url = f'/products?category={d.cat}&limit=30'
    r1 = call(PORT_AFTER, 'GET', url, d.cust)
    hits = [call(PORT_AFTER, 'GET', url, d.cust) for _ in range(7)]
    r2 = hits[0]
    hit_ms = statistics.median(h.ms for h in hits)
    s.line('BEFORE', f"GET list first time  -> {r1.status} X-Cache: {r1.headers.get('x-cache')}  {r1.ms:.1f} ms  ({len(r1.body)} bytes)")
    s.line('AFTER', f"GET list again       -> {r2.status} X-Cache: {r2.headers.get('x-cache')}  {r2.ms:.1f} ms (median of 7 repeats: {hit_ms:.1f} ms; one sample is noisy: the DB work saved is small)")
    ver = redis_cli('get', 'trendova:products:ver') or '0'
    params = {'page': 1, 'limit': 30, 'category_id': str(d.cat), 'sort_by': 'created_at', 'order': 'desc'}
    key = f"trendova:products:list:v{ver}:{hashlib.sha1(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()[:24]}"
    call(PORT_AFTER, 'GET', f'/products/{d.pid}', d.cust)
    ttl_list, ttl_det = redis_cli('ttl', key), redis_cli('ttl', f'trendova:products:detail:{d.pid}')
    s.line('AFTER', f'key TTLs: list {ttl_list} s (60 s +-10 %), detail {ttl_det} s (300 s +-10 %)')
    d.admin_write()
    e = call(PORT_AFTER, 'PUT', f'/products/{d.pid}', d.admin, form={'price': '77.77'})
    r3 = call(PORT_AFTER, 'GET', url, d.cust)
    price = [i['price'] for i in r3.json()['items'] if i['id'] == d.pid]
    s.line('BEFORE', f"admin edits price -> {e.status}; next GET list -> X-Cache: {r3.headers.get('x-cache')} (cache invalidated), price now {price}")
    d0 = call(PORT_AFTER, 'GET', f'/products/{d.pid}', d.cust).json()['stock']['quantity']
    call(PORT_AFTER, 'POST', '/orders', d.cust, js={'items': [{'product_id': d.pid, 'quantity': 5}]})
    dd = call(PORT_AFTER, 'GET', f'/products/{d.pid}', d.cust)
    s.line('AFTER', f"order of 5 units -> detail X-Cache: {dd.headers.get('x-cache')} (static part from Redis) but stock {d0} -> {dd.json()['stock']['quantity']} at once (never cached)")
    # Redis down
    down_codes = None
    try:
        docker('stop', '-t', '2', cname('redis'))
        a, b = call(PORT_AFTER, 'GET', url, d.cust), call(PORT_AFTER, 'GET', f'/products/{d.pid}', d.cust)
        down_codes = (a.status, a.headers.get('x-cache'), b.status, b.headers.get('x-cache'))
    finally:
        docker('start', cname('redis'))
        wait_container('redis')
    s.line('AFTER', f'Redis STOPPED -> list {down_codes[0]} X-Cache: {down_codes[1]}, detail {down_codes[2]} X-Cache: {down_codes[3]} (fail-open, served from the database); Redis started again')
    time.sleep(2.2)   # circuit-breaker window
    # stampede on a brand-new key
    adm = d.admin
    urllib.request.urlopen(urllib.request.Request(f'http://localhost:{PORT_AFTER}/internal/cache-stats/reset', method='POST', headers={'Authorization': 'Bearer ' + adm}), timeout=10).read()
    cold = f'/products?category={d.cat}&limit=30&minPrice=0.01&maxPrice={uuid.uuid4().int % 100000 + 1000}'
    with concurrent.futures.ThreadPoolExecutor(20) as ex:
        codes = list(ex.map(lambda _: call(PORT_AFTER, 'GET', cold, d.cust).status, range(20)))
    stats = json.loads(urllib.request.urlopen(urllib.request.Request(f'http://localhost:{PORT_AFTER}/internal/cache-stats', headers={'Authorization': 'Bearer ' + adm}), timeout=10).read())
    s.line('AFTER', f"stampede: 20 concurrent cold requests -> statuses {sorted(set(codes))}, database fills = {stats['fills']} (waited for the winner: {stats['stampede_waits']})")
    ok = (r1.headers.get('x-cache') == 'MISS' and r2.headers.get('x-cache') == 'HIT' and r3.headers.get('x-cache') == 'MISS' and price == ['77.77']
          and dd.json()['stock']['quantity'] == d0 - 5 and down_codes[0] == 200 and down_codes[2] == 200 and stats['fills'] == 1 and set(codes) == {200})
    d.facts['cache'] = {'miss_ms': round(r1.ms, 1), 'hit_ms': round(hit_ms, 1), 'ttl_list': ttl_list, 'ttl_detail': ttl_det, 'fills': stats['fills']}
    return s.result(ok, f"MISS {r1.ms:.1f} ms -> HIT {hit_ms:.1f} ms (median); edit visible at once; stock live; fail-open; 1 fill for 20 requests" if ok else 'a cache expectation failed',
                    'X-Cache headers, redis-cli TTL, GET /internal/cache-stats (admin)')


def step6(d):
    s = Step(6, 'ETag / 304', 'bytes on the wire for a repeated request, and what happens after an admin edit')
    d.fixtures()
    path = f'/products/{d.pid}'
    r1 = call(PORT_AFTER, 'GET', path, d.cust, headers={'Accept-Encoding': 'identity'})
    etag = r1.headers.get('etag')
    s.line('BEFORE', f'GET {path}                    -> {r1.status}, {len(r1.body)} bytes, {r1.ms:.1f} ms, ETag {etag}, Cache-Control: {r1.headers.get("cache-control")}')
    r2 = call(PORT_AFTER, 'GET', path, d.cust, headers={'If-None-Match': etag})
    s.line('AFTER', f'GET {path} (If-None-Match)     -> {r2.status}, {len(r2.body)} bytes, {r2.ms:.1f} ms (body not resent, ETag still sent: {r2.headers.get("etag") == etag})')
    d.admin_write()
    call(PORT_AFTER, 'PUT', path, d.admin, form={'price': '88.88'})
    r3 = call(PORT_AFTER, 'GET', path, d.cust, headers={'If-None-Match': etag})
    new = r3.headers.get('etag')
    s.line('BEFORE', f'after admin edit, OLD etag           -> {r3.status}, {len(r3.body)} bytes, new ETag {new}, price {r3.json()["price"] if r3.status == 200 else "-"}')
    r4 = call(PORT_AFTER, 'GET', path, d.cust, headers={'If-None-Match': new})
    s.line('AFTER', f'after admin edit, NEW etag           -> {r4.status}, {len(r4.body)} bytes')
    lst = f'/products?category={d.cat}&limit=30'
    l1 = call(PORT_AFTER, 'GET', lst, d.cust, headers={'Accept-Encoding': 'identity'})
    lz = call(PORT_AFTER, 'GET', lst, d.cust, headers={'Accept-Encoding': 'gzip'})
    l2 = call(PORT_AFTER, 'GET', lst, d.cust, headers={'If-None-Match': l1.headers.get('etag'), 'Accept-Encoding': 'gzip'})
    s.line('AFTER', f"list page: identity {len(l1.body)} bytes, gzip {len(lz.body)} bytes ({lz.headers.get('content-encoding')}), same ETag: {l1.headers.get('etag') == lz.headers.get('etag')}; with If-None-Match -> {l2.status}, {len(l2.body)} bytes")
    saved = len(r1.body) - len(r2.body)
    ok = (r1.status == 200 and r2.status == 304 and len(r2.body) == 0 and r3.status == 200 and new != etag and r4.status == 304
          and l1.headers.get('etag') == lz.headers.get('etag') and l2.status == 304)
    d.facts['etag'] = {'bytes_full': len(r1.body), 'bytes_304': len(r2.body), 'list_identity': len(l1.body), 'list_gzip': len(lz.body)}
    return s.result(ok, f'304 saves {saved} bytes on this detail; old ETag -> 200 + new ETag; new ETag -> 304; gzip keeps the same ETag' if ok else 'an ETag expectation failed',
                    'curl-equivalent requests with If-None-Match (see docs/req3/http_cache.md)')


def freshness_check(d, n):
    stale = 0
    for i in range(n):
        price = f'{20 + i}.{i:02d}'
        call(PORT_AFTER, 'GET', f'/products/{d.pid}', d.cust)
        call(PORT_AFTER, 'GET', f'/products?category={d.cat}&limit=30', d.cust)
        call(PORT_AFTER, 'PUT', f'/products/{d.pid}', d.admin, form={'price': price})
        dd = call(PORT_AFTER, 'GET', f'/products/{d.pid}', d.cust).json()
        ll = call(PORT_AFTER, 'GET', f'/products?category={d.cat}&limit=30', d.cust).json()
        item = [x for x in ll['items'] if x['id'] == d.pid]
        stale += (dd['price'] != price) + (not item or item[0]['price'] != price)
    d.admin_write()
    return stale


def browser_check(d):
    etags, hits, total = {}, 0, 0
    urls = [f'/products?category={c}&limit=20' for c in range(1, 9)] + [f'/products/{p}' for p in range(1, 9)]
    for _ in range(3):
        for u in urls:
            r = call(PORT_AFTER, 'GET', u, d.cust, headers={'If-None-Match': etags[u]} if u in etags else None)
            total += 1
            hits += r.status == 304
            if r.status == 200 and r.headers.get('etag'):
                etags[u] = r.headers['etag']
    return hits / total if total else None


def step7(d):
    scen = 'list,search' if d.quick else 'list,detail,search,my_orders'
    per = max(3, d.duration // len(scen.split(',')))
    s = Step(7, 'Load test: the same k6 workload, interleaved BEFORE / AFTER' + ('' if d.quick else ' / BEFORE / AFTER'),
             f'p50/p95/p99, req/s, errors per endpoint; k6 scenarios {scen} (20 closed-loop VUs each, {per} s per scenario, same script as the full profile)')
    d.fixtures()
    env = {'SCEN_S': str(per), 'WARMUP_S': '3', 'GAP_S': '1', 'CUSTOMERS': '10' if d.quick else '20'}
    runs = {'BEFORE': [], 'AFTER': []}
    stamp = datetime.now().strftime('%H%M%S')
    try:
        for i, cond in enumerate(['BEFORE', 'AFTER'] if d.quick else ['BEFORE', 'AFTER', 'BEFORE', 'AFTER']):
            if not d.quick:   # --quick has no time for index DDL: BEFORE there = baseline code on the final indexes
                abr.set_indexes(cond == 'AFTER')
            svc = 'app-v0' if cond == 'BEFORE' else 'app'
            data = abr.run_k6(f'demo_{stamp}_{cond.lower()}{i // 2 + 1}', svc, only=scen, env=env)
            runs[cond].append(data['endpoints'])
            e = data['endpoints'].get('list', {})
            con.p(f"          run {i + 1}/{2 if d.quick else 4} {cond:<6}: list {e.get('req_per_s')} req/s p50 {fmt(e.get('p50_ms'))} ms p95 {fmt(e.get('p95_ms'))} ms | errors {e.get('error_rate')}")
    finally:
        abr.set_indexes(True)
    keys = [k for k in ('list', 'list_deep', 'detail', 'search', 'my_orders') if k in runs['BEFORE'][0]]

    def mean(cond, ep, k):
        v = [r.get(ep, {}).get(k) for r in runs[cond]]
        v = [x for x in v if x is not None]
        return statistics.mean(v) if v else None
    con.p()
    con.p(f"  {'endpoint':<14}|{'p50 ms':>17}|{'p95 ms':>17}|{'p99 ms':>17}|{'req/s':>15}|{'err %':>11}|{'factor p95':>11}")
    con.p(f"  {'':<14}|{'before->after':>17}|{'before->after':>17}|{'before->after':>17}|{'before->after':>15}|{'b->a':>11}|")
    for ep in keys:
        cells, fac = [], None
        for k, nd in (('p50_ms', 0), ('p95_ms', 0), ('p99_ms', 0), ('req_per_s', 1)):
            b, a = mean('BEFORE', ep, k), mean('AFTER', ep, k)
            cells.append(f'{fmt(b, nd)}->{fmt(a, nd)}')
            if k == 'p95_ms':
                fac = ratio(b, a)
        eb, ea = mean('BEFORE', ep, 'error_rate'), mean('AFTER', ep, 'error_rate')
        con.p(f"  {ep:<14}|{cells[0]:>17}|{cells[1]:>17}|{cells[2]:>17}|{cells[3]:>15}|{fmt(None if eb is None else eb * 100, 1) + '->' + fmt(None if ea is None else ea * 100, 1):>11}|{rtxt(fac):>11}")
    t = [sum(r.get(k, {}).get('req_per_s') or 0 for k in keys) for r in runs['BEFORE']]
    drift = abs(t[0] - t[1]) / max(t) * 100 if len(t) == 2 and all(t) else None   # needs the two BEFORE runs
    s.line('BEFORE', f'control: the two BEFORE runs differ by {fmt(drift, 1)} % in req/s (the noise floor of this laptop)' if drift is not None else 'control: --quick runs one BEFORE/AFTER pair, so there is no drift control; a clear 1.2x is required instead (full demo: 2 pairs)')
    errs = [mean(c, k, 'error_rate') for c in ('BEFORE', 'AFTER') for k in keys]
    stale = freshness_check(d, 5 if d.quick else 15)
    nm = browser_check(d)
    s.line('AFTER', f'freshness under load profile: stale_reads = {stale} (must be 0); browser-like client not_modified_ratio = {fmt(None if nm is None else nm * 100, 1)} %')
    # whole-profile summary: sum of req/s over the endpoints, mean of each percentile over the endpoints
    tot = lambda cond, k: statistics.mean(mean(cond, ep, k) for ep in keys if mean(cond, ep, k) is not None)
    p50f, p95f, p99f = (ratio(tot('BEFORE', k), tot('AFTER', k)) for k in ('p50_ms', 'p95_ms', 'p99_ms'))
    sum_b = sum(mean('BEFORE', ep, 'req_per_s') or 0 for ep in keys)
    sum_a = sum(mean('AFTER', ep, 'req_per_s') or 0 for ep in keys)
    thr = ratio(sum_a, sum_b)
    beyond_noise = thr is not None and (abs(thr - 1) * 100 > drift if drift is not None else thr >= 1.2)   # --quick: single pair, no drift control -> require a clear 1.2x
    d.facts['load'] = {'p50_factor': p50f, 'p95_factor': p95f, 'p99_factor': p99f, 'throughput_factor': thr, 'drift_pct': drift, 'stale_reads': stale, 'not_modified_ratio': nm,
                       'before': {k: tot('BEFORE', k) for k in ('p50_ms', 'p95_ms', 'p99_ms')}, 'after': {k: tot('AFTER', k) for k in ('p50_ms', 'p95_ms', 'p99_ms')}}
    ok = bool(beyond_noise and thr > 1 and p95f and p95f > 1 and stale == 0 and not any(errs))
    msg = (f'throughput {rtxt(thr)}, p50 {rtxt(p50f)}, p95 {rtxt(p95f)}, p99 {rtxt(p99f)} better; stale_reads {stale}' if ok
           else ('WITHIN NOISE: the difference is smaller than the drift between the two BEFORE runs, no gain is claimed' if not beyond_noise else 'worse or errors or stale reads'))
    return s.result(ok, msg, f'k6 loadtest/k6/main.js (ONLY={scen}) -> loadtest/results/demo_{stamp}_*.json; short runs, so tails are rough')


def step8(d):
    s = Step(8, 'Test suite', 'pytest -m "req3_phase1 or req3_phase2" inside the tester container (live stack, real Redis/replica/gRPC)')
    extra = []
    marker = 'req3_phase1 or req3_phase2'
    if d.quick:
        con.p('  QUICK SUBSET (no container stop/start tests): test_etag, test_freshness; the full suite runs without --quick')
        files = [f'tests/req3/{f}.py' for f in ('test_etag', 'test_freshness')]
        cmd = ['docker', 'compose', '--profile', 'test', 'run', '--rm', '--no-deps', 'tester', *files, '-m', marker, '-q', '--no-header', '-rs']
        r = st.sh(cmd)
        out = r.stdout + r.stderr
        rc = r.returncode
    else:
        st.sh(['docker', 'compose', '--profile', 'test', 'build', 'tester'])
        rc, _, out = st.run_tests(marker)
    summary = (re.findall(r'^.*\b(?:passed|failed|error)\b.* in [\d.]+s.*$', out, re.M) or ['no pytest summary'])[-1].strip()
    counts = {k: int((re.search(rf'(\d+) {k}', summary) or [0, 0])[1]) for k in ('passed', 'failed', 'skipped', 'error')}
    for line in out.splitlines():
        if line.startswith('FAILED') or line.startswith('ERROR'):
            con.p('    ' + line[:150])
    s.line('AFTER', summary)
    d.facts['tests'] = counts
    return s.result(rc == 0 and counts['passed'] > 0, f"{counts['passed']} passed, {counts['failed']} failed, {counts['skipped']} skipped" + (' (quick subset)' if d.quick else ''), 'docker compose --profile test run tester -m "req3_phase1 or req3_phase2"')


STEPS = {0: step0, 1: step1, 2: step2, 3: step3, 4: step4, 5: step5, 6: step6, 7: step7, 8: step8}


def scoreboard(d, results):
    f = d.facts
    L = f.get('load', {})
    ex = f.get('explain_ratios') or []
    rows = [
        ('Realistic data volume', 'dev DB: 12 orders (optimization_log)', ' / '.join(f"{k}={v:,}" for k, v in (f.get('counts') or {}).items() if k in ('products', 'orders', 'order_items')) or NOT_MEASURED, results.get(0)),
        ('EXPLAIN / query speed-up', 'filesort + full scans', f'hot queries {rtxt(min(ex)) if ex else NOT_MEASURED}..{rtxt(max(ex)) if ex else NOT_MEASURED} faster', results.get(1)),
        ('N+1 fixed (DB + gRPC)', f"gRPC N calls ({(f.get('grpc_calls') or {}).get('naive')})", f"1 call ({(f.get('grpc_calls') or {}).get('batch')}); SELECTs constant", results.get(2)),
        ('Index write cost (info)', 'without new index', f"{(f.get('index_write_cost') or {}).get('without', NOT_MEASURED)} -> {(f.get('index_write_cost') or {}).get('with', NOT_MEASURED)} orders/s", results.get(3)),
        ('Read replica + read-your-writes', 'every read on the primary', 'author sees own write; lag proven real' if (f.get('ryw') or {}).get('author_sees') else NOT_MEASURED, results.get(4)),
        ('Redis cache (TTL, invalidation)', 'every request hits MySQL', f"MISS {(f.get('cache') or {}).get('miss_ms', NOT_MEASURED)} ms -> HIT {(f.get('cache') or {}).get('hit_ms', NOT_MEASURED)} ms", results.get(5)),
        ('ETag / 304', f"{(f.get('etag') or {}).get('bytes_full', NOT_MEASURED)} bytes every time", f"{(f.get('etag') or {}).get('bytes_304', NOT_MEASURED)} bytes on 304", results.get(6)),
        ('Load test p50/p95/p99', f"{fmt((L.get('before') or {}).get('p50_ms'), 0)}/{fmt((L.get('before') or {}).get('p95_ms'), 0)}/{fmt((L.get('before') or {}).get('p99_ms'), 0)} ms",
         f"{fmt((L.get('after') or {}).get('p50_ms'), 0)}/{fmt((L.get('after') or {}).get('p95_ms'), 0)}/{fmt((L.get('after') or {}).get('p99_ms'), 0)} ms ({rtxt(L.get('p95_factor'))} p95)", results.get(7)),
        ('A product edit is visible at once', 'n/a', f"stale_reads = {L.get('stale_reads', NOT_MEASURED)}", None if L.get('stale_reads') is None else (L.get('stale_reads') == 0 and results.get(5) and results.get(6) and results.get(4))),
        ('Test suite', 'n/a', f"{(f.get('tests') or {}).get('passed', NOT_MEASURED)} passed, {(f.get('tests') or {}).get('failed', NOT_MEASURED)} failed", results.get(8)),
    ]
    return rows


def print_scoreboard(rows, title='FINAL SCOREBOARD'):
    con.p()
    con.p(con.paint('36;1', f'[STEP 9/{TOTAL_STEPS}] {title}'))
    w = [34, 34, 46]
    con.p('  ' + f"{'Requirement':<{w[0]}}| {'BEFORE':<{w[1]}}| {'AFTER':<{w[2]}}| RESULT")
    con.p('  ' + '-' * (sum(w) + 12))
    for name, b, a, ok in rows:
        info = name.endswith('(info)')
        con.p('  ' + f'{name:<{w[0]}}| {str(b)[:w[1] - 1]:<{w[1]}}| {str(a)[:w[2] - 1]:<{w[2]}}| ' + ('INFO' if info else con.tag(ok)))
    gate = [ok for name, _, _, ok in rows if not name.endswith('(info)')]
    overall = all(ok is True for ok in gate)
    con.p()
    con.p(f"  OVERALL: {con.tag(overall)}" + ('' if overall else '   (a row is FAIL or NOT MEASURED)'))
    return overall


# ----------------------------------------------------------------------------- restore + saved results
def restore(d):
    """Always leave the system in its final state."""
    con.p()
    con.p('restoring the final state ...')
    for svc in ('redis', 'db-replica', 'inventory-service', 'app'):
        r = docker('inspect', '-f', '{{.State.Running}}', cname(svc))
        if r.stdout.strip() != 'true':
            docker('start', cname(svc))
            wait_container(svc)
    try:
        replica_sql('STOP REPLICA SQL_THREAD; CHANGE REPLICATION SOURCE TO SOURCE_DELAY=0; START REPLICA SQL_THREAD;')
        abr.set_indexes(True)
    except Exception as e:  # never hide the real error of the run
        con.p(f'  restore warning: {e}')
    st.cleanup()
    con.p('  indexes = final set, replication delay = 0, redis/replica/inventory running, req3_demo_* data removed')


def from_results():
    if not SAVED.exists():
        con.p('no saved demo results yet: run the demo once (py scripts/demo_req3.py --quick)')
        return 1
    data = json.loads(SAVED.read_text(encoding='utf-8'))
    con.p(con.paint('33;1', f"=== SAVED RESULTS (nothing is run live) - recorded {data['finished_at']} by `{data['mode']}` ==="))
    for n, name in sorted((int(k), v) for k, v in data['step_titles'].items()):
        ok = data['results'].get(str(n))
        con.p(f'  step {n}: {name:<64} {con.tag(ok)}  ({data["step_seconds"].get(str(n), "?")} s)')
    rows = [tuple(r) for r in data['scoreboard']]
    for i, r in enumerate(rows):
        rows[i] = (r[0], r[1], r[2], r[3])
    overall = print_scoreboard(rows, 'SCOREBOARD (SAVED RESULTS)')
    fin = sorted(RESULTS.glob('final_V*_r*.json'))
    if fin:
        con.p()
        con.p('  saved final interleaved benchmark (loadtest/results/final_*.json), mixed_total mean per variant:')
        agg = {}
        for p in fin:
            m = re.match(r'final_(V\d)_r(\d+)\.json', p.name)
            if m:
                e = json.loads(p.read_text()).get('endpoints', {}).get('mixed_total')
                if e:
                    agg.setdefault(m.group(1), []).append(e)
        for v, es in sorted(agg.items()):
            con.p(f"    {v}: {statistics.mean(e['req_per_s'] for e in es):.2f} req/s, p50 {statistics.mean(e['p50_ms'] for e in es):.0f} ms, p95 {statistics.mean(e['p95_ms'] for e in es):.0f} ms, p99 {statistics.mean(e['p99_ms'] for e in es):.0f} ms ({len(es)} runs)")
    return 0 if overall else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--pause', action='store_true')
    ap.add_argument('--step', type=int)
    ap.add_argument('--duration', type=int)
    ap.add_argument('--from-results', action='store_true')
    ap.add_argument('--no-color', action='store_true')
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding='ascii', errors='replace')
    except Exception:
        pass
    enable_color(args.no_color)
    if args.from_results:
        return from_results()
    t0 = time.time()
    d = Demo(args)
    mode = 'demo_req3.py' + (' --quick' if args.quick else '') + (f' --step {args.step}' if args.step is not None else '')
    con.p(con.paint('36;1', f'=== Requirement 3 demo ({mode}) - {datetime.now():%Y-%m-%d %H:%M:%S} ==='))
    results, titles, secs = {}, {}, {}
    wanted = [args.step] if args.step is not None else list(range(0, 9))
    try:
        if args.step is not None and args.step != 0:
            st.compose('--profile', 'ab', 'up', '-d', '--no-deps', 'app-v0', 'app-v1', 'app-diag')
            for p in (PORT_BEFORE, PORT_V1, PORT_DIAG):
                st.wait_url(f'http://localhost:{p}/health', 60)
        for n in wanted:
            if n == 9:
                continue
            step = STEPS[n](d)
            results[n], titles[n], secs[n] = step.ok, step.title, step.facts.get('seconds')
            if args.pause and n != wanted[-1]:
                input('  -- press Enter for the next step --')
    except KeyboardInterrupt:
        con.p('interrupted')
    finally:
        restore(d)
    rows = scoreboard(d, results)
    overall = print_scoreboard(rows) if args.step is None else None
    runtime = time.time() - t0
    con.p(f'  runtime: {runtime:.0f} s ({runtime / 60:.1f} min)')
    if args.step is None:
        SAVED.write_text(json.dumps({'mode': mode, 'finished_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'runtime_s': round(runtime), 'results': {str(k): v for k, v in results.items()},
                                     'step_titles': {str(k): v for k, v in titles.items()}, 'step_seconds': {str(k): v for k, v in secs.items()},
                                     'scoreboard': [list(r[:3]) + [r[3]] for r in rows], 'facts': d.facts}, indent=1, default=str), encoding='utf-8')
        return 0 if overall else 1
    return 0 if all(v is True for v in results.values()) else 1


if __name__ == '__main__':
    sys.exit(main())

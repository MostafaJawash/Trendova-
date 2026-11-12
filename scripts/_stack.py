"""Shared helpers for scripts/run_phase1.py, run_phase2.py and demo_req3.py. Stdlib only (host Python 3.12/3.13)."""
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / 'loadtest' / 'results'
APP = 'http://localhost:8000'


def sh(cmd, check=False, input=None, timeout=None, **kw):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, input=input, timeout=timeout, check=check, **kw)


def compose(*args, **kw):
    return sh(['docker', 'compose', *args], **kw)


def mysql(sql, host='db'):
    r = compose('exec', '-T', host, 'sh', '-c', 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" ecommerce -N -B 2>/dev/null', input=sql)
    return r.stdout.strip()


def http_json(path, token=None, method='GET', body=None, timeout=30):
    req = urllib.request.Request(APP + path, method=method, data=json.dumps(body).encode() if body is not None else None)
    if body is not None:
        req.add_header('Content-Type', 'application/json')
    if token:
        req.add_header('Authorization', 'Bearer ' + token)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b'null')


def wait_url(url, timeout=180):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(2)
    return False


def replica_status():
    out = compose('exec', '-T', 'db-replica', 'sh', '-c', 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "SHOW REPLICA STATUS\\G" 2>/dev/null').stdout
    return {k.strip(): v.strip() for k, sep, v in (line.partition(':') for line in out.splitlines()) if sep}


def wait_replication(timeout=240):
    end = time.time() + timeout
    while time.time() < end:
        st = replica_status()
        if st.get('Replica_IO_Running') == 'Yes' and st.get('Replica_SQL_Running') == 'Yes':
            return True
        time.sleep(3)
    return False


def row_counts():
    sql = "SELECT (SELECT COUNT(*) FROM users),(SELECT COUNT(*) FROM products),(SELECT COUNT(*) FROM orders),(SELECT COUNT(*) FROM order_items),(SELECT COUNT(*) FROM categories)"
    vals = mysql(sql).split()
    return dict(zip(('users', 'products', 'orders', 'order_items', 'categories'), (int(v) for v in vals))) if len(vals) == 5 else {}


def inventory_rows():
    r = compose('exec', '-T', 'inventory-db', 'psql', '-U', 'inventory', '-d', 'inventory', '-At', '-c', 'SELECT COUNT(*) FROM inventory')
    return int(r.stdout.strip() or 0)


def seed_if_empty(log=print):
    c = row_counts()
    if c.get('products', 0) >= 20000 and c.get('orders', 0) >= 300000:
        log(f'seed: dataset already present {c}')
        return True
    log('seed: dataset missing -> running scripts/seed.py (about 90 s)')
    r = subprocess.run([sys.executable, 'scripts/seed.py'], cwd=ROOT)
    return r.returncode == 0


def start_stack(log=print):
    r = compose('up', '-d', '--build', 'app', 'db-replica', 'replica-init', 'redis')
    if r.returncode != 0:
        log(r.stderr[-800:])
        return False
    ok = wait_url(APP + '/health') and wait_replication()
    return ok


def run_tests(markers, extra=(), log=print):
    """Run pytest inside the `tester` container; returns (returncode, summary_line, full_output)."""
    cmd = ['docker', 'compose', '--profile', 'test', 'run', '--rm', '--no-deps', 'tester', 'tests', '-m', markers, '-q', '--no-header', '-rs', *extra]
    r = sh(cmd)
    out = r.stdout + r.stderr
    m = re.findall(r'^.*\b(?:passed|failed|error|skipped)\b.* in [\d.]+s.*$', out, re.M)
    return r.returncode, (m[-1].strip() if m else 'no pytest summary'), out


def k6_smoke(label, only='mixed'):
    """20 s k6 smoke through scripts/bench.py (--quick profile); returns (ok, json)."""
    r = subprocess.run([sys.executable, 'scripts/bench.py', '--label', label, '--only', only, '--quick'], cwd=ROOT, capture_output=True, text=True)
    p = RESULTS / f'{label}.json'
    if r.returncode != 0 or not p.exists():
        return False, None
    data = json.loads(p.read_text(encoding='utf-8'))
    errs = [e['error_rate'] for e in data['endpoints'].values() if e.get('error_rate') is not None]
    return bool(data['endpoints']) and max(errs or [0]) < 0.01, data


def cleanup():
    subprocess.run([sys.executable, 'scripts/req3_cleanup.py'], cwd=ROOT, capture_output=True)

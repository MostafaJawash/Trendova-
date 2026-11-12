#!/usr/bin/env python3
"""Interleaved A/B runner (Requirement 3). Stdlib only, Windows-friendly; heavy lifting happens in containers.

Why: runs separated in time are NOT comparable on this laptop (same code gave 127 vs 66 req/s). Every before/after
claim therefore comes from variants run ROUND-ROBIN in ONE session (V0,V1,..,V0,V1,..), each run against its own
app container, with an unchanged CONTROL run at the start and at the end of the session to show drift.

Variants (containers of the compose profile "ab", started by `scripts/ab_build.py up`):
  V0   baseline image (last commit before any Req 3 change), the new indexes DROPPED   -> :8010
  V1   new code: indexes + query/N+1 fixes, replica/cache/etag off                      -> :8011
  V2   V1 + USE_READ_REPLICA                                                            -> :8012
  V3   V2 + CACHE_ENABLED                                                               -> :8013
  V4   V3 + ETAG_ENABLED (the FINAL service `app`)                                      -> :8000
  prev / new   per-change A/B of one code change (previous image vs current)            -> :8020 / :8000

  py scripts/ab_runner.py --prefix final --variants V0,V1,V2,V3,V4 --rounds 2 --control V4
  py scripts/ab_runner.py --prefix chg_a --variants prev,new --rounds 2 --only list --quick
Results: loadtest/results/<prefix>_<variant>_r<round>.json (+ .stats.json with docker stats), <prefix>_session.json.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / 'loadtest' / 'results'
NEW_INDEXES = [
    ('products', 'idx_products_active_created', 'is_active, created_at, id'),
    ('products', 'idx_products_cat_active_created', 'category_id, is_active, created_at, id'),
    ('orders', 'idx_orders_user_created', 'user_id, created_at, id'),
]
# The ORIGINAL schema had two single-column indexes that migration req3_002 drops (the composites cover them).
OLD_INDEXES = [('products', 'idx_category_id', 'category_id'), ('orders', 'idx_orders_user_id', 'user_id')]
VARIANTS = {
    'V0': dict(service='app-v0', port=8010, indexes=False),
    'V1': dict(service='app-v1', port=8011, indexes=True),
    'V2': dict(service='app-v2', port=8012, indexes=True),
    'V3': dict(service='app-v3', port=8013, indexes=True),
    'V4': dict(service='app', port=8000, indexes=True),
    'prev': dict(service='app-prev', port=8020, indexes=True),
    'new': dict(service='app', port=8000, indexes=True),
}


def sh(cmd, **kw):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, **kw)


def mysql(sql, host='db'):
    r = sh(['docker', 'compose', 'exec', '-T', host, 'sh', '-c', 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" ecommerce -N 2>/dev/null'], input=sql)
    return r.stdout.strip()


def index_names():
    out = mysql("SELECT index_name FROM information_schema.statistics WHERE table_schema='ecommerce' GROUP BY table_name,index_name")
    return set(out.split())


def set_indexes(on):
    """on=True: the FINAL index set (3 composites, the two redundant single-column indexes dropped).
    on=False: the ORIGINAL set (composites dropped, idx_category_id / idx_orders_user_id present) = the before state."""
    have = index_names()
    for table, name, cols in NEW_INDEXES:   # create first, drop afterwards: a foreign key always has an index
        if on and name not in have:
            mysql(f'CREATE INDEX {name} ON {table} ({cols})')
    for table, name, col in OLD_INDEXES:
        if not on and name not in have:
            mysql(f'CREATE INDEX {name} ON {table} ({col})')
        if on and name in have:
            mysql(f'DROP INDEX {name} ON {table}')
    for table, name, cols in NEW_INDEXES:
        if not on and name in have:
            mysql(f'DROP INDEX {name} ON {table}')
    wait_replica_sync()


def replica_present():
    r = sh(['docker', 'compose', 'ps', '--status', 'running', '--format', '{{.Service}}'])
    return 'db-replica' in r.stdout.split()


def wait_replica_sync(timeout=180):
    """After DDL/bulk writes the replica must have caught up before a run starts (it is not part of the numbers)."""
    if not replica_present():
        return
    end = time.time() + timeout
    while time.time() < end:
        s = sh(['docker', 'compose', 'exec', '-T', 'db-replica', 'sh', '-c', 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "SHOW REPLICA STATUS\\G" 2>/dev/null']).stdout
        m = re.search(r'Seconds_Behind_Source: (\d+)', s or '')
        if m and m.group(1) == '0' and 'read all relay log' in s:
            return
        time.sleep(2)


def health(port, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(f'http://localhost:{port}/health', timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(2)
    return False


def sample_stats(stop, samples):
    while not stop.is_set():
        r = sh(['docker', 'stats', '--no-stream', '--format', '{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}'])
        snap = {}
        for line in r.stdout.splitlines():
            name, cpu, mem = (line.split('|') + ['', ''])[:3]
            if name.startswith('trendova-req3-') and re.search(r'-(db|db-replica|redis|app|app-v\d|app-prev|inventory-service|inventory-db)-1$', name):
                snap[name] = {'cpu': float(cpu.strip('%') or 0), 'mem': mem}
        samples.append(snap)
        stop.wait(4)


def run_k6(label, service, only=None, quick=False, script='main.js', env=None, keyset=False):
    base = f"http://{service}:8000/api/v1"
    cmd = ['docker', 'compose', '--profile', 'loadtest', 'run', '--rm', '--no-deps', '-e', f'RUN_LABEL={label}',
           '-e', f'BASE_URL={base}', '-e', 'DEEP_PAGE_MODE=' + ('keyset' if keyset else 'offset')]
    if only:
        cmd += ['-e', f'ONLY={only}']
    if quick:
        cmd += ['-e', 'QUICK=1']
    for k, v in (env or {}).items():
        cmd += ['-e', f'{k}={v}']
    cmd += ['k6', 'run', f'/loadtest/k6/{script}']
    samples, stop = [], threading.Event()
    t = threading.Thread(target=sample_stats, args=(stop, samples), daemon=True)
    t.start()
    t0 = time.time()
    res = sh(cmd)
    stop.set(); t.join(timeout=10)
    out = RESULTS / f'{label}.json'
    if not out.exists():
        print(res.stdout[-1500:], res.stderr[-1500:])
        raise SystemExit(f'k6 produced no results for {label}')
    # per-container CPU: mean and max of the samples taken during the run
    agg = {}
    for snap in samples:
        for name, v in snap.items():
            agg.setdefault(name, []).append(v['cpu'])
    stats = {n.replace('trendova-req3-', ''): {'cpu_mean': round(sum(c) / len(c), 1), 'cpu_max': round(max(c), 1), 'samples': len(c)} for n, c in agg.items()}
    (RESULTS / f'{label}.stats.json').write_text(json.dumps({'seconds': round(time.time() - t0), 'docker_stats': stats}, indent=1))
    return json.loads(out.read_text(encoding='utf-8'))


def session_notes():
    notes = {'started': time.strftime('%Y-%m-%d %H:%M:%S'), 'host_power_plan': None, 'docker_total_memory_bytes': None, 'wslconfig': None}
    r = sh(['powershell', '-NoProfile', '-Command', 'powercfg /getactivescheme'])
    notes['host_power_plan'] = (r.stdout or r.stderr).strip() or None
    r = sh(['docker', 'info', '--format', '{{.MemTotal}} {{.NCPU}}'])
    if r.stdout.strip():
        mem, cpu = r.stdout.split()[:2]
        notes['docker_total_memory_bytes'], notes['docker_ncpu'] = int(mem), int(cpu)
    cfg = Path(os.path.expanduser('~/.wslconfig'))
    notes['wslconfig'] = cfg.read_text() if cfg.exists() else 'no .wslconfig (WSL2 defaults)'
    return notes


def cache_stats(port, reset=False):
    """Admin-only in-process counters of the app worker behind `port` (hit/miss/bypass/fills); None if unavailable."""
    try:
        req = urllib.request.Request(f'http://localhost:{port}/api/v1/auth/login', data=json.dumps({'email': 'admin@example.com', 'password': 'ChangeMe123!'}).encode(), headers={'Content-Type': 'application/json'})
        tok = json.loads(urllib.request.urlopen(req, timeout=10).read())['access_token']
        path = '/internal/cache-stats/reset' if reset else '/internal/cache-stats'
        r = urllib.request.urlopen(urllib.request.Request(f'http://localhost:{port}{path}', method='POST' if reset else 'GET', headers={'Authorization': 'Bearer ' + tok}), timeout=10)
        return None if reset else json.loads(r.read())
    except Exception:
        return None


def one(prefix, variant, rnd, args, tag=None):
    v = VARIANTS[variant]
    set_indexes(v['indexes'])
    if not health(v['port']):
        raise SystemExit(f'{variant}: {v["service"]} is not healthy on :{v["port"]}')
    label = f'{prefix}_{tag or variant}_r{rnd}'
    t0 = time.time()
    cache_api = variant in ('V3', 'V4', 'new')
    if cache_api:
        cache_stats(v['port'], reset=True)
    data = run_k6(label, v['service'], args.only, args.quick, keyset=args.keyset)
    if cache_api:
        st_ = cache_stats(v['port'])
        if st_:
            (RESULTS / f'{label}.cache.json').write_text(json.dumps(st_, indent=1))
    print(f'  {label:<34} {time.time() - t0:5.0f}s  ' + '  '.join(
        f"{k}={e['req_per_s']}/s p50={e['p50_ms']:.0f}ms" for k, e in data['endpoints'].items() if k in ('list', 'detail', 'search', 'my_orders', 'create_order', 'mixed_total')), flush=True)
    return label


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--prefix', required=True)
    ap.add_argument('--variants', default='V0,V1,V2,V3,V4')
    ap.add_argument('--rounds', type=int, default=2)
    ap.add_argument('--control', help='variant run once before and once after all rounds (drift check)')
    ap.add_argument('--only', choices=['list', 'detail', 'search', 'my_orders', 'create_order', 'mixed'])
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--keyset', action='store_true', help='DEEP_PAGE_MODE=keyset')
    ap.add_argument('--cold', help='extra COLD-cache run of this variant at the end (Redis flushed first)')
    args = ap.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    variants = args.variants.split(',')
    session = session_notes()
    session.update(prefix=args.prefix, variants=variants, rounds=args.rounds, control=args.control, only=args.only, quick=args.quick, runs=[])
    print(f"session {args.prefix}: variants={variants} rounds={args.rounds} control={args.control} only={args.only} quick={args.quick}")
    print('power plan:', session['host_power_plan'], '| docker mem:', session['docker_total_memory_bytes'])
    try:
        if args.control:
            session['runs'].append(one(args.prefix, args.control, 0, args, tag=f'{args.control}_control_start'))
        for rnd in range(1, args.rounds + 1):
            for v in variants:
                session['runs'].append(one(args.prefix, v, rnd, args))
        if args.control:
            session['runs'].append(one(args.prefix, args.control, 0, args, tag=f'{args.control}_control_end'))
        if args.cold:
            sh(['docker', 'compose', 'exec', '-T', 'redis', 'redis-cli', 'flushall'])
            session['runs'].append(one(args.prefix, args.cold, 0, args, tag=f'{args.cold}_cold'))
    finally:
        set_indexes(True)  # always leave the new indexes in place
        session['finished'] = time.strftime('%Y-%m-%d %H:%M:%S')
        (RESULTS / f'{args.prefix}_session.json').write_text(json.dumps(session, indent=1))


if __name__ == '__main__':
    main()

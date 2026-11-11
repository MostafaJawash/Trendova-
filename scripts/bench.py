#!/usr/bin/env python3
"""Run the fixed k6 workload against the compose stack and print a compact table.

Stdlib only, works on Windows/Linux/macOS, Python 3.12+.

  py scripts/bench.py --label before
  py scripts/bench.py --label idx_orders --only my_orders
  py scripts/bench.py --label smoke --quick
  py scripts/bench.py --compare before after_indexes after_db
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / 'loadtest' / 'results'
ONLY_CHOICES = ['list', 'detail', 'search', 'my_orders', 'create_order', 'mixed']
ORDER = ['list', 'list_deep', 'detail', 'search', 'my_orders', 'create_order',
         'mixed_list', 'mixed_detail', 'mixed_search', 'mixed_orders', 'mixed_create', 'mixed_total']


def wait_health(url, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(2)
    return False


def fmt(v, digits=1):
    return '-' if v is None else f'{v:.{digits}f}'


def print_table(path):
    data = json.loads(path.read_text(encoding='utf-8'))
    print(f"\nresults: {path.relative_to(ROOT)}  (only={data['only']}, quick={data['quick']}, deep_page_mode={data.get('deep_page_mode')})")
    head = f"{'endpoint':<14}{'reqs':>8}{'req/s':>9}{'p50 ms':>10}{'p95 ms':>10}{'p99 ms':>10}{'err %':>8}"
    print(head)
    print('-' * len(head))
    for name in ORDER:
        e = data['endpoints'].get(name)
        if e:
            err = None if e['error_rate'] is None else e['error_rate'] * 100
            print(f"{name:<14}{e['count']:>8}{fmt(e['req_per_s'], 2):>9}{fmt(e['p50_ms']):>10}{fmt(e['p95_ms']):>10}{fmt(e['p99_ms']):>10}{fmt(err, 2):>8}")
    if data.get('dropped_iterations'):
        print(f"dropped iterations (open-loop arrival not sustained): {data['dropped_iterations']}")


def compare(labels):
    rows = {}
    for label in labels:
        p = RESULTS / f'{label}.json'
        if not p.exists():
            sys.exit(f'missing {p}')
        rows[label] = json.loads(p.read_text(encoding='utf-8'))['endpoints']
    for metric, title in (('p50_ms', 'p50 ms'), ('p95_ms', 'p95 ms'), ('p99_ms', 'p99 ms'), ('req_per_s', 'req/s')):
        print(f'\n{title}')
        print(f"{'endpoint':<14}" + ''.join(f'{l:>16}' for l in labels))
        for name in ORDER:
            if any(name in rows[l] for l in labels):
                print(f'{name:<14}' + ''.join(f"{fmt(rows[l].get(name, {}).get(metric), 2 if metric == 'req_per_s' else 1):>16}" for l in labels))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--label', help='run label; writes loadtest/results/<label>.json')
    ap.add_argument('--only', choices=ONLY_CHOICES, help='run a single endpoint scenario')
    ap.add_argument('--quick', action='store_true', help='~20s smoke profile')
    ap.add_argument('--deep-page-mode', choices=['offset', 'keyset'], default='offset')
    ap.add_argument('--health-url', default='http://localhost:8000/health')
    ap.add_argument('--compare', nargs='+', metavar='LABEL', help='print a side-by-side table of existing results')
    args = ap.parse_args()

    if args.compare:
        compare(args.compare)
        return
    if not args.label:
        ap.error('--label is required')

    print(f'checking app health at {args.health_url} ...')
    if not wait_health(args.health_url):
        sys.exit('app is not healthy; start the stack first (docker compose up -d)')
    RESULTS.mkdir(parents=True, exist_ok=True)
    cmd = ['docker', 'compose', '--profile', 'loadtest', 'run', '--rm', '--no-deps',
           '-e', f'RUN_LABEL={args.label}', '-e', f'DEEP_PAGE_MODE={args.deep_page_mode}']
    if args.only:
        cmd += ['-e', f'ONLY={args.only}']
    if args.quick:
        cmd += ['-e', 'QUICK=1']
    cmd += ['k6']
    print('running k6 (this takes several minutes for the full profile) ...')
    t0 = time.time()
    res = subprocess.run(cmd, cwd=ROOT)
    print(f'k6 exited with {res.returncode} after {time.time() - t0:.0f}s')
    out = RESULTS / f'{args.label}.json'
    if not out.exists():
        sys.exit('k6 produced no results file')
    print_table(out)
    sys.exit(0 if res.returncode == 0 else res.returncode)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Quick INTERLEAVED A/B of one GET path between two running app containers (per-change measurements).

Single sequential client over keep-alive connections, blocks of N requests alternate A,B,A,B... for R rounds, so both
variants see the same machine state. Reports p50/p95/mean ms per variant, per round and overall, plus the verdict
"within noise" when the variants differ by less than the round-to-round spread of the SAME variant.

  py scripts/ab_endpoint.py --name chg_a_list --path "/products?category=3&limit=20" --a 8020 --b 8000 --as admin
Port map: 8000 app (final), 8010 v0, 8011 v1, 8012 v2, 8013 v3, 8020 prev.
"""
import argparse
import http.client
import json
import statistics
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / 'loadtest' / 'results'


def login(port, email, password):
    c = http.client.HTTPConnection('localhost', port, timeout=30)
    c.request('POST', '/api/v1/auth/login', json.dumps({'email': email, 'password': password}), {'Content-Type': 'application/json'})
    r = c.getresponse()
    body = json.loads(r.read())
    if r.status != 200:
        raise SystemExit(f'login failed on :{port}: {r.status} {body}')
    return body['access_token']


def timed_block(conn, path, headers, n):
    out, hdr = [], {}
    for _ in range(n):
        t = time.perf_counter()
        try:
            conn.request('GET', '/api/v1' + path, headers=headers)
            r = conn.getresponse()
            body = r.read()
        except (ConnectionError, http.client.HTTPException, OSError):   # idle keep-alive closed by the server: reconnect once
            conn.close()
            t = time.perf_counter()
            conn.request('GET', '/api/v1' + path, headers=headers)
            r = conn.getresponse()
            body = r.read()
        out.append((time.perf_counter() - t) * 1000)
        if r.status != 200:
            raise SystemExit(f'{path}: HTTP {r.status} {body[:200]}')
        hdr = dict(r.getheaders())
    return out, hdr


def com_select():
    """Primary's global SELECT counter (variant independent: counts what really reached MySQL)."""
    r = subprocess.run(['docker', 'compose', 'exec', '-T', 'db', 'sh', '-c', 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N -e "SHOW GLOBAL STATUS LIKE \'Com_select\'" 2>/dev/null'], cwd=ROOT, capture_output=True, text=True)
    return int(r.stdout.split()[-1])


def selects_for(conn, path, headers):
    """SELECT statements one request makes (idle noise subtracted; needs a quiet system)."""
    a = com_select(); b = com_select(); noise = b - a
    timed_block(conn, path, headers, 1)
    c = com_select()
    return c - b - noise - 0


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--name', required=True)
    ap.add_argument('--path', required=True, action='append', help='GET path under /api/v1 (repeatable: requests rotate over them)')
    ap.add_argument('--path-b', action='append', help='different path(s) for variant B (e.g. keyset cursor vs offset page)')
    ap.add_argument('--a', type=int, required=True)
    ap.add_argument('--b', type=int, required=True)
    ap.add_argument('--as', dest='who', default='customer', choices=['customer', 'admin'])
    ap.add_argument('--rounds', type=int, default=3)
    ap.add_argument('--block', type=int, default=60)
    ap.add_argument('--password', default='LoadTest123!')
    ap.add_argument('--admin-email', default='admin@example.com')
    ap.add_argument('--admin-password', default='ChangeMe123!')
    args = ap.parse_args()
    who = (args.admin_email, args.admin_password) if args.who == 'admin' else ('customer001@loadtest.example', args.password)
    ports = {'A': args.a, 'B': args.b}
    tok = {k: login(p, *who) for k, p in ports.items()}
    conns = {k: http.client.HTTPConnection('localhost', p, timeout=60) for k, p in ports.items()}
    paths_for = {'A': args.path, 'B': args.path_b or args.path}
    paths = args.path
    for k in 'AB':   # warm-up (not recorded)
        for p in paths_for[k]:
            timed_block(conns[k], p, {'Authorization': 'Bearer ' + tok[k]}, 10)
    sel = {k: [selects_for(conns[k], p, {'Authorization': 'Bearer ' + tok[k]}) for p in paths_for[k]] for k in 'AB'}
    samples = {'A': [[] for _ in range(args.rounds)], 'B': [[] for _ in range(args.rounds)]}
    hdr = {}
    for rnd in range(args.rounds):
        for k in ('A', 'B') if rnd % 2 == 0 else ('B', 'A'):   # ABBA ordering removes first-in-round bias
            for p in paths_for[k]:
                xs, h = timed_block(conns[k], p, {'Authorization': 'Bearer ' + tok[k]}, args.block)
                samples[k][rnd] += xs
                hdr[k] = h
    res = {'name': args.name, 'paths': paths_for, 'as': args.who, 'rounds': args.rounds, 'block': args.block, 'ports': ports, 'variants': {}}
    for k in 'AB':
        allx = [x for r in samples[k] for x in r]
        res['variants'][k] = {
            'p50_ms': round(statistics.median(allx), 2), 'p95_ms': round(pct(allx, .95), 2), 'mean_ms': round(statistics.mean(allx), 2), 'n': len(allx),
            'round_p50_ms': [round(statistics.median(r), 2) for r in samples[k]],
            'selects_per_request': sel[k], 'x_cache': hdr[k].get('X-Cache'), 'x_db_query_count': hdr[k].get('X-DB-Query-Count'),
        }
    a, b = res['variants']['A'], res['variants']['B']
    spread = max(max(v['round_p50_ms']) - min(v['round_p50_ms']) for v in (a, b))
    diff = a['p50_ms'] - b['p50_ms']
    res['p50_diff_ms_A_minus_B'] = round(diff, 2)
    res['round_spread_ms'] = round(spread, 2)
    res['ratio_A_over_B'] = round(a['p50_ms'] / b['p50_ms'], 3) if b['p50_ms'] else None
    res['verdict'] = 'within noise' if abs(diff) <= spread else ('B faster' if diff > 0 else 'A faster')
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f'{args.name}.json').write_text(json.dumps(res, indent=1))
    print(f"{args.name}: A(:{args.a}) p50={a['p50_ms']} p95={a['p95_ms']} rounds={a['round_p50_ms']} selects={a['selects_per_request']} | B(:{args.b}) p50={b['p50_ms']} p95={b['p95_ms']} rounds={b['round_p50_ms']} selects={b['selects_per_request']} | ratio A/B={res['ratio_A_over_B']} spread={res['round_spread_ms']}ms -> {res['verdict']}")


if __name__ == '__main__':
    main()

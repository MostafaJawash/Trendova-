#!/usr/bin/env python3
"""Generate the numeric tables of docs/req3/REPORT_AR.md from loadtest/results/*.json (real numbers only).

The Arabic explanations are written by hand; this script only fills the blocks between
  <!-- TABLE:name -->  and  <!-- /TABLE:name -->
and is idempotent. Tables use ASCII digits and Latin column names so they render the same everywhere.

  py scripts/make_report.py --prefix final
"""
import argparse
import json
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / 'loadtest' / 'results'
REPORT = ROOT / 'docs' / 'req3' / 'REPORT_AR.md'
VARIANTS = ['V0', 'V1', 'V2', 'V3', 'V4']
ENDPOINTS = ['list', 'list_deep', 'detail', 'search', 'my_orders', 'create_order', 'mixed_total']
NAMES = {'V0': 'V0 before', 'V1': 'V1 +indexes +N+1', 'V2': 'V2 +replica', 'V3': 'V3 +Redis cache', 'V4': 'V4 +ETag (final)'}


def load(label):
    p = RESULTS / f'{label}.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else None


def rounds(prefix, v):
    out, r = [], 1
    while (d := load(f'{prefix}_{v}_r{r}')) is not None:
        out.append(d)
        r += 1
    return out


def mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.mean(xs) if xs else None


def fmt(x, n=1):
    return 'NOT MEASURED' if x is None else f'{x:.{n}f}'


def agg(runs, ep, key):
    return mean([r['endpoints'].get(ep, {}).get(key) for r in runs])


def main_table(prefix):
    runs = {v: rounds(prefix, v) for v in VARIANTS}
    n = {v: len(runs[v]) for v in VARIANTS}
    lines = [f"Mean of {min(n.values()) if n else 0}-{max(n.values()) if n else 0} interleaved rounds per variant (same session, same k6 profile, 0 = no data).", '',
             '| endpoint | variant | p50 ms | p95 ms | p99 ms | req/s | error % | p50 of each round |', '|---|---|---:|---:|---:|---:|---:|---|']
    for ep in ENDPOINTS:
        for v in VARIANTS:
            if not runs[v]:
                continue
            err = agg(runs[v], ep, 'error_rate')
            lines.append(f"| {ep} | {NAMES[v]} | {fmt(agg(runs[v], ep, 'p50_ms'))} | {fmt(agg(runs[v], ep, 'p95_ms'))} | {fmt(agg(runs[v], ep, 'p99_ms'))} | "
                         f"{fmt(agg(runs[v], ep, 'req_per_s'), 2)} | {fmt(None if err is None else err * 100, 2)} | {' / '.join(fmt(r['endpoints'].get(ep, {}).get('p50_ms'), 0) for r in runs[v])} |")
    lines += ['', '**V0 -> V4 factor (final vs before)**', '', '| endpoint | p50 factor | p95 factor | p99 factor | req/s factor |', '|---|---:|---:|---:|---:|']
    for ep in ENDPOINTS:
        row = []
        for key, inv in (('p50_ms', True), ('p95_ms', True), ('p99_ms', True), ('req_per_s', False)):
            a, b = agg(runs['V0'], ep, key), agg(runs['V4'], ep, key)
            row.append('NOT MEASURED' if not a or not b else f'{(a / b if inv else b / a):.2f}x')
        lines.append(f'| {ep} | ' + ' | '.join(row) + ' |')
    return '\n'.join(lines)


def noise_table(prefix):
    lines = ['| variant | round | mixed_total req/s | p50 ms | p95 ms | p99 ms |', '|---|---:|---:|---:|---:|---:|']
    for v in VARIANTS:
        for i, d in enumerate(rounds(prefix, v), 1):
            e = d['endpoints'].get('mixed_total', {})
            lines.append(f"| {v} | {i} | {fmt(e.get('req_per_s'), 2)} | {fmt(e.get('p50_ms'))} | {fmt(e.get('p95_ms'))} | {fmt(e.get('p99_ms'))} |")
    for tag in ('V4_control_start', 'V4_cold', 'V4_control_end'):
        d = load(f'{prefix}_{tag}_r0')
        if d:
            e = d['endpoints'].get('mixed_total', {})
            lines.append(f"| {tag} | - | {fmt(e.get('req_per_s'), 2)} | {fmt(e.get('p50_ms'))} | {fmt(e.get('p95_ms'))} | {fmt(e.get('p99_ms'))} |")
    s, e = load(f'{prefix}_V4_control_start_r0'), load(f'{prefix}_V4_control_end_r0')
    if s and e:
        a, b = s['endpoints']['mixed_total']['req_per_s'], e['endpoints']['mixed_total']['req_per_s']
        lines += ['', f'Drift inside the session (unchanged V4, start vs end): {a:.2f} -> {b:.2f} req/s ({(b - a) / a * 100:+.1f} %).']
    return '\n'.join(lines)


def cold_table(prefix):
    cold, warm = load(f'{prefix}_V4_cold_r0'), rounds(prefix, 'V4')
    if not cold or not warm:
        return 'NOT MEASURED'
    lines = ['| endpoint | cold p50 ms | cold p99 ms | warm p50 ms | warm p99 ms | cold req/s | warm req/s |', '|---|---:|---:|---:|---:|---:|---:|']
    for ep in ENDPOINTS:
        c = cold['endpoints'].get(ep)
        if c:
            lines.append(f"| {ep} | {fmt(c['p50_ms'])} | {fmt(c['p99_ms'])} | {fmt(agg(warm, ep, 'p50_ms'))} | {fmt(agg(warm, ep, 'p99_ms'))} | {fmt(c['req_per_s'], 2)} | {fmt(agg(warm, ep, 'req_per_s'), 2)} |")
    return '\n'.join(lines)


CONTAINER_OF = {'V0': 'app-v0-1', 'V1': 'app-v1-1', 'V2': 'app-v2-1', 'V3': 'app-v3-1', 'V4': 'app-1'}


def stats_table(prefix):
    lines = ['Mean / max CPU % sampled every ~4 s by `docker stats` while the variant was under load (one core = 100 %). `app` = the application container under test only.', '',
             '| variant | app (under test) | primary db | replica | redis | inventory-service |', '|---|---:|---:|---:|---:|---:|']
    for v in VARIANTS:
        acc = {}
        for r in range(1, 9):
            p = RESULTS / f'{prefix}_{v}_r{r}.stats.json'
            if not p.exists():
                break
            for name, s in json.loads(p.read_text())['docker_stats'].items():
                key = ('app' if name == CONTAINER_OF[v] else 'db' if name == 'db-1' else 'replica' if 'replica' in name else 'redis' if 'redis' in name else 'inv' if name == 'inventory-service-1' else None)
                if key:
                    acc.setdefault(key, []).append((s['cpu_mean'], s['cpu_max']))
        if acc:
            cell = lambda k: (f"{mean([a for a, _ in acc[k]]):.0f} / {max(b for _, b in acc[k]):.0f}" if k in acc else '-')
            lines.append(f"| {NAMES[v]} | {cell('app')} | {cell('db')} | {cell('replica')} | {cell('redis')} | {cell('inv')} |")
    return chr(10).join(lines)


def freshness_table(prefix):
    d = load(f'{prefix}_freshness_r0') or load(f'{prefix}_freshness')
    if not d:
        return 'NOT MEASURED'
    return '\n'.join(['| metric | value |', '|---|---:|',
                      f"| stale_reads (must be 0) | {d['stale_reads']} |", f"| freshness checks (detail + list after each admin edit) | {d['fresh_checks']} |",
                      f"| not_modified_ratio (browser-like client, If-None-Match) | {fmt(None if d['not_modified_ratio'] is None else d['not_modified_ratio'] * 100, 1)} % |",
                      f"| read-after-write p50 / p99 ms | {fmt(d['read_after_write_p50_ms'])} / {fmt(d['read_after_write_p99_ms'])} |",
                      f"| HTTP failures | {fmt(None if d['http_req_failed_rate'] is None else d['http_req_failed_rate'] * 100, 2)} % |"])


def index_table(_):
    lines = ['| run | condition | req/s | p50 ms | p95 ms | p99 ms |', '|---|---|---:|---:|---:|---:|']
    for o in ('my_orders', 'create_order'):
        for lab in ('1A', '2B', '3B', '4A'):
            d = load(f'ab_idx_{o}_{lab}')
            if d:
                e = d['endpoints'][o]
                lines.append(f"| {o} {lab} | {'no new indexes' if lab[1] == 'A' else 'indexes'} | {fmt(e['req_per_s'], 2)} | {fmt(e['p50_ms'])} | {fmt(e['p95_ms'])} | {fmt(e['p99_ms'])} |")
    return '\n'.join(lines)


def cache_table(prefix):
    lines = ['| run | hit | miss | bypass | fills | hit ratio |', '|---|---:|---:|---:|---:|---:|']
    for p in sorted(RESULTS.glob(f'{prefix}_*.cache.json')):
        s = json.loads(p.read_text())
        lines.append(f"| {p.stem.replace('.cache', '')} | {s['hit']} | {s['miss']} | {s['bypass']} | {s['fills']} | {fmt(None if s['hit_ratio'] is None else s['hit_ratio'] * 100, 1)} % |")
    return '\n'.join(lines) if len(lines) > 2 else 'NOT MEASURED'


TABLES = {'main': main_table, 'noise': noise_table, 'cold': cold_table, 'stats': stats_table, 'freshness': freshness_table, 'index': index_table, 'cache': cache_table}


EXPLAIN_PAIRS = [
    ('category page (limit 20)', 'list: category page 1 (limit 20)', 'list: category page 1 (limit 20)'),
    ('newest page (limit 20)', 'list: newest page 1', 'list: newest page 1'),
    ('deep page 900 (offset) vs keyset cursor', 'list: deep page 900 (offset 17,980)', 'list: keyset deep page (cursor)'),
    ('search "wireless"', 'search: "wireless" (limit 20)', 'search: "wireless" (limit 20)'),
    ('my orders, hottest user (limit 10)', 'my_orders: hottest user page 1 (limit 10)', 'my_orders: hottest user page 1 (limit 10)'),
]


def _page_plan(sc):
    for p in (sc or {}).get('plans', []):
        low = p['sql'].lower()
        if 'count(' not in low and 'from favorites' not in low and 'order_items.order_id' not in low:
            return p
    return None


def explain_table(_):
    b, a = RESULTS / 'explain_demo_before.json', RESULTS / 'explain_demo_after.json'
    if not (b.exists() and a.exists()):
        return 'NOT MEASURED'
    bj, aj = json.loads(b.read_text())['scenarios'], json.loads(a.read_text())['scenarios']
    lines = ['EXPLAIN ANALYZE of the page query the application really emits (before = baseline code + original indexes; after = final code + composite indexes).', '',
             '| query | before ms | before rows examined | before plan | after ms | after rows examined | after plan | speed-up |', '|---|---:|---:|---|---:|---:|---|---:|']
    for title, bn, an in EXPLAIN_PAIRS:
        pb, pa = _page_plan(bj.get(bn)), _page_plan(aj.get(an))
        if not pb or not pa:
            continue
        plan = lambda p: ('full scan' if p['full_scan'] else 'index') + (' + filesort' if p['filesort'] else '')
        lines.append(f"| {title} | {pb['time_ms']:.3f} | {pb['max_rows_examined']} | {plan(pb)} | {pa['time_ms']:.3f} | {pa['max_rows_examined']} | {plan(pa)} | {pb['time_ms'] / pa['time_ms']:.1f}x |")
    return chr(10).join(lines)


TABLES['explain'] = explain_table


def signif_table(prefix):
    runs = {v: rounds(prefix, v) for v in VARIANTS}
    lines = ['Is the V0 -> V4 change bigger than the noise? Noise = the largest relative difference between the TWO rounds of the same variant (req/s) for that endpoint; a change smaller than the noise is NOT claimed.', '',
             '| endpoint | V0 req/s | V4 req/s | change | noise (max round-to-round spread) | verdict |', '|---|---:|---:|---:|---:|---|']
    for ep in ENDPOINTS:
        if not runs['V0'] or not runs['V4']:
            break
        spreads = []
        for v in VARIANTS:
            xs = [r['endpoints'].get(ep, {}).get('req_per_s') for r in runs[v]]
            if len(xs) == 2 and all(xs):
                spreads.append(abs(xs[0] - xs[1]) / ((xs[0] + xs[1]) / 2) * 100)
        a, b = agg(runs['V0'], ep, 'req_per_s'), agg(runs['V4'], ep, 'req_per_s')
        if not a or not b or not spreads:
            continue
        ch = (b - a) / a * 100
        noise = max(spreads)
        verdict = ('above noise: IMPROVEMENT' if ch > 0 else 'above noise: WORSE') if abs(ch) > noise else 'within noise: no claim'
        lines.append(f'| {ep} | {a:.2f} | {b:.2f} | {ch:+.1f} % | {noise:.1f} % | {verdict} |')
    return chr(10).join(lines)


TABLES['signif'] = signif_table


def fill(text, prefix):
    for name, fn in TABLES.items():
        pat = re.compile(rf'(<!-- TABLE:{name} -->)(.*?)(<!-- /TABLE:{name} -->)', re.S)
        if pat.search(text):
            text = pat.sub(lambda m: f'{m.group(1)}\n{fn(prefix)}\n{m.group(3)}', text)
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--prefix', default='final')
    args = ap.parse_args()
    if not REPORT.exists():
        raise SystemExit(f'{REPORT} does not exist yet (write the Arabic text with <!-- TABLE:main --> markers first)')
    REPORT.write_text(fill(REPORT.read_text(encoding='utf-8'), args.prefix), encoding='utf-8')
    print(f'updated {REPORT.relative_to(ROOT)} from {RESULTS.relative_to(ROOT)}/{args.prefix}_*.json')


if __name__ == '__main__':
    main()

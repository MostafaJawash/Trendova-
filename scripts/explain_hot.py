#!/usr/bin/env python3
"""EXPLAIN ANALYZE of the hot queries, captured from the REAL application code (runs INSIDE the app container).

It calls the service functions behind the hot endpoints, records every SELECT the ORM emits (with its parameters),
runs `EXPLAIN ANALYZE` on each and prints statements / time / rows. Run it against any image, so the same script
shows BEFORE (previous image) and AFTER (current image):

  docker compose run --rm --no-deps -v ./scripts:/app/scripts -e LABEL=after app python scripts/explain_hot.py
  docker compose run --rm --no-deps -v ./scripts:/app/scripts -e LABEL=before --entrypoint python trendova-req3-prev ... (see ab_build.py)

Writes loadtest/results/explain_<LABEL>.json when /app/loadtest/results is mounted, always prints a table.
"""
import json
import os
import re
import sys
import time
from datetime import datetime
sys.path.insert(0, '/app')
os.environ.setdefault('INVENTORY_MODE', 'fake')
from sqlalchemy import event  # noqa: E402
import app.core.model_registry  # noqa: E402,F401  (registers every mapped model)
from app.core.database import SessionLocal, engine  # noqa: E402
from app.modules.products import service as products, repository as prepo  # noqa: E402
from app.modules.orders import service as orders  # noqa: E402

captured = []


@event.listens_for(engine, 'before_cursor_execute')
def _capture(conn, cursor, statement, parameters, context, executemany):
    if statement.lstrip().upper().startswith('SELECT'):
        captured.append((statement, parameters))


def scenarios(db):
    user = 1001   # hottest seeded customer (about 16k orders)
    yield 'list: category page 1 (limit 20)', lambda: products.products(db, user, 1, 20, category_id=3)
    yield 'list: deep page 900 (offset 17,980)', lambda: products.products(db, user, 900, 20)
    yield 'list: newest page 1', lambda: products.products(db, user, 1, 20)
    if hasattr(prepo, 'decode_cursor'):
        first = products.products(db, user, 899, 20)
        cur = first.get('next_cursor')
        if cur:
            yield 'list: keyset deep page (cursor)', lambda: products.products(db, user, 1, 20, cursor=cur)
    yield 'search: "wireless" (limit 20)', lambda: products.products(db, user, 1, 20, search='wireless')
    yield 'my_orders: hottest user page 1 (limit 10)', lambda: orders.list_orders(db, user, 1, 10)
    yield 'my_orders: hottest user limit 50', lambda: orders.list_orders(db, user, 1, 50)
    yield 'detail: product 12345', lambda: products.product(db, 12345, user, False)
    if not os.getenv('SKIP_DASHBOARD'):   # 13-30 s on this dataset (see optimization_log entry 8)
        yield 'dashboard stats', lambda: orders.stats(db)


def analyze(stmt, params):
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        sql = cur.mogrify(stmt, params) if params else stmt
        cur.execute('EXPLAIN ANALYZE ' + sql)
        text = '\n'.join(r[0] for r in cur.fetchall())
    finally:
        raw.close()
    top = re.search(r'actual time=[\d.]+\.\.([\d.]+) rows=(\d+)', text)
    scans = re.findall(r'(Table scan|Index lookup|Index range scan|Index scan|Covering index[^\n(]*|Single-row index lookup|Filter)[^\n]*? on (\w+)(?: using (\w+))?', text)
    rows = [int(x) for x in re.findall(r'actual time=[\d.]+\.\.[\d.]+ rows=(\d+)', text)]
    return {'time_ms': float(top.group(1)) if top else None, 'top_rows': int(top.group(2)) if top else None,
            'max_rows_examined': max(rows) if rows else None, 'filesort': 'Sort:' in text, 'full_scan': 'Table scan' in text,
            'access': [f'{a.strip()} {t}' + (f' using {k}' if k else '') for a, t, k in scans][:3]}


def main():
    label = os.getenv('LABEL', 'run')
    out = {'label': label, 'generated_at': datetime.utcnow().isoformat() + 'Z', 'scenarios': {}}
    with SessionLocal() as db:
        for name, fn in scenarios(db):
            captured.clear()
            t = time.perf_counter(); fn(); wall = (time.perf_counter() - t) * 1000
            stmts = list(captured)
            plans = [dict(sql=re.sub(r'\s+', ' ', s)[:110], **analyze(s, p)) for s, p in stmts]
            out['scenarios'][name] = {'wall_ms': round(wall, 2), 'select_statements': len(stmts), 'plans': plans}
            print(f'\n{name}\n  wall {wall:.1f} ms, {len(stmts)} SELECT statement(s)')
            for pl in plans:
                print(f"   {pl['time_ms']!s:>8} ms  rows={pl['max_rows_examined']!s:>6}  scan={'YES' if pl['full_scan'] else 'no '}  sort={'YES' if pl['filesort'] else 'no '}  {pl['sql'][:80]}")
    d = '/app/loadtest/results'
    if os.path.isdir(d):
        with open(f'{d}/explain_{label}.json', 'w') as f:
            json.dump(out, f, indent=1)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Print how many SQL statements each hot endpoint issues (needs DB_QUERY_COUNT=1 on the app).

  $env:DB_QUERY_COUNT=1; docker compose up -d app      # PowerShell
  py scripts/query_counts.py

A count that grows with `limit` is an N+1; a constant count is not. Stdlib only.
"""
import argparse
import json
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument('--base', default='http://localhost:8000/api/v1')
ap.add_argument('--email', default='customer050@loadtest.example')
ap.add_argument('--password', default='LoadTest123!')
args = ap.parse_args()


def call(method, path, token=None, body=None):
    req = urllib.request.Request(args.base + path, method=method, data=json.dumps(body).encode() if body else None)
    req.add_header('Content-Type', 'application/json')
    if token:
        req.add_header('Authorization', 'Bearer ' + token)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.headers.get('X-DB-Query-Count'), json.loads(r.read() or b'null')


status, _, data = call('POST', '/auth/login', body={'email': args.email, 'password': args.password})
token = data['access_token']
rows = []


def probe(label, method, path, body=None):
    status, count, _ = call(method, path, token, body)
    if count is None:
        raise SystemExit('no X-DB-Query-Count header: start the app with DB_QUERY_COUNT=1')
    rows.append((label, status, int(count)))


probe('GET /auth/me (auth only)', 'GET', '/auth/me')
for limit in (1, 5, 20, 100):
    probe(f'GET /products?category=1&limit={limit}', 'GET', f'/products?category=1&limit={limit}')
probe('GET /products?search=headphones&limit=20', 'GET', '/products?search=headphones&limit=20')
probe('GET /products?limit=20&page=900 (deep)', 'GET', '/products?limit=20&page=900')
probe('GET /products/5 (detail)', 'GET', '/products/5')
for limit in (1, 10, 50, 100):
    probe(f'GET /orders?limit={limit}', 'GET', f'/orders?limit={limit}')
probe('POST /orders (3 items)', 'POST', '/orders', {'items': [{'product_id': 5, 'quantity': 1}, {'product_id': 17, 'quantity': 1}, {'product_id': 230, 'quantity': 1}]})

print(f"{'request':<48}{'status':>7}{'SQL statements':>16}")
print('-' * 71)
for label, status, count in rows:
    print(f'{label:<48}{status:>7}{count:>16}')

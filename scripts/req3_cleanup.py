#!/usr/bin/env python3
"""Remove every throw-away row created by Requirement 3 tests / demos / k6 freshness runs. Stdlib only; uses docker.

Names that identify throw-away data: `req3_test_*` (pytest), `req3_demo_*` (scripts/demo_req3.py), `req3_k6_*` (k6 freshness).
Seeded data, benchmark orders of the seeded `customerNNN@loadtest.example` users and Docker volumes are never touched.

  py scripts/req3_cleanup.py            # delete
  py scripts/req3_cleanup.py --count    # only report how many rows would be removed
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAT = r"(name LIKE 'req3\_%' OR name LIKE 'e2e-%')"   # e2e-*: legacy name of the first e2e test runs
USERS = r"SELECT id FROM users WHERE (email LIKE 'req3\_%' OR email LIKE 'e2e-%')"
PRODUCTS = f"SELECT id FROM products WHERE {PAT}"
CATS = f"SELECT id FROM categories WHERE {PAT}"
STEPS = [
    ('notifications', f"DELETE FROM notifications WHERE user_id IN ({USERS})"),
    ('favorites', f"DELETE FROM favorites WHERE user_id IN ({USERS}) OR product_id IN ({PRODUCTS})"),
    ('order_items', f"DELETE FROM order_items WHERE product_id IN ({PRODUCTS}) OR order_id IN (SELECT id FROM orders WHERE user_id IN ({USERS}))"),
    ('orders', f"DELETE FROM orders WHERE user_id IN ({USERS}) AND id NOT IN (SELECT order_id FROM (SELECT order_id FROM order_items) x)"),
    ('users', r"DELETE FROM users WHERE (email LIKE 'req3\_%' OR email LIKE 'e2e-%')"),
    ('products', f"DELETE FROM products WHERE {PAT}"),
    ('categories', f"DELETE FROM categories WHERE {PAT}"),
]


def mysql(sql):
    r = subprocess.run(['docker', 'compose', 'exec', '-T', 'db', 'sh', '-c', 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" ecommerce -N -B 2>/dev/null'],
                       cwd=ROOT, input=sql, capture_output=True, text=True)
    return r.stdout.strip()


def main():
    if '--count' in sys.argv:
        for what, sql in (('users', USERS), ('products', PRODUCTS), ('categories', CATS)):
            print(what, mysql(sql.replace('SELECT id', 'SELECT COUNT(*)')))
        return
    ids = mysql(PRODUCTS).split()
    for _, sql in STEPS:
        mysql(sql)
    # orders of throw-away users that still had items of OTHER products (rare): remove leftovers explicitly
    mysql(f"DELETE FROM orders WHERE user_id NOT IN (SELECT id FROM users)")
    if ids:   # warehouse rows of throw-away products (and the high-id rows of the GetStockBatch tests)
        subprocess.run(['docker', 'compose', 'exec', '-T', 'inventory-db', 'psql', '-U', 'inventory', '-d', 'inventory', '-c',
                        f"DELETE FROM inventory WHERE product_id IN ({','.join(ids)}) OR product_id >= 9000000000"], cwd=ROOT, capture_output=True)
    print('req3 throw-away data removed (products:', len(ids), ')')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Deterministic, idempotent bulk seeder for Requirement 3 (performance work).

Host requirements: Python 3.12+ (stdlib only) and a running compose stack.
Everything heavy happens inside the containers:
  * MySQL  : batched multi-row INSERT IGNORE piped to the `mysql` client in `db`.
  * Postgres: COPY into a temp table piped to `psql` in `inventory-db`, then
              INSERT .. ON CONFLICT DO NOTHING (one stock row per product id).
  * bcrypt : ONE hash is computed inside the `app` container and reused.

Determinism: fixed RNG seed, explicit primary keys, INSERT IGNORE. Re-running
with the same arguments produces the same rows and never duplicates them; a
table that already holds at least the requested number of rows is skipped.

Assumes a fresh database (apart from the admin the app creates at startup):
explicit ids 1..N are used for categories/products/orders/order_items and
1001..1000+U for users, so rows created by hand with colliding ids would be
silently skipped by INSERT IGNORE.

Examples:
  py scripts/seed.py
  py scripts/seed.py --products 2000 --users 200 --orders 20000   # quick dev set
"""
import argparse
import bisect
import hashlib
import random
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USER_ID_BASE = 1000
KNOWN_CUSTOMERS = 50

# Vocabulary shared with loadtest/k6/main.js (search terms are drawn from here).
ADJECTIVES = ['Wireless', 'Portable', 'Ergonomic', 'Premium', 'Compact', 'Smart', 'Classic',
              'Rugged', 'Ultra', 'Eco', 'Vintage', 'Modern', 'Deluxe', 'Mini', 'Pro']
NOUNS = ['Headphones', 'Keyboard', 'Backpack', 'Lamp', 'Blender', 'Monitor', 'Notebook',
         'Speaker', 'Charger', 'Jacket', 'Sneakers', 'Watch', 'Camera', 'Router', 'Mug',
         'Chair', 'Desk', 'Kettle', 'Tablet', 'Sunglasses']
CATEGORY_NAMES = ['Electronics', 'Home', 'Books', 'Fashion', 'Sports', 'Toys', 'Garden', 'Beauty',
                  'Grocery', 'Automotive', 'Office', 'Pets', 'Music', 'Movies', 'Games', 'Tools',
                  'Health', 'Baby', 'Jewelry', 'Travel']
STATUSES = ['delivered', 'shipped', 'confirmed', 'pending', 'cancelled']
STATUS_WEIGHTS = [60, 10, 8, 7, 15]


def log(msg):
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def read_env():
    env = {}
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip()
    return env


def compose(*args, stdin=None, check=True, capture=True):
    cmd = ['docker', 'compose', *args]
    res = subprocess.run(cmd, cwd=ROOT, input=stdin, capture_output=capture, text=True, encoding='utf-8')
    if check and res.returncode != 0:
        sys.exit(f'command failed: {" ".join(cmd)}\n{res.stderr or res.stdout}')
    return res


class Mysql:
    """One long-lived mysql client process fed with SQL text on stdin."""

    def __init__(self, password):
        self.password = password

    def _base(self):
        return ['exec', '-T', '-e', f'MYSQL_PWD={self.password}', 'db', 'mysql', '-uroot', '--default-character-set=utf8mb4', 'ecommerce']

    def scalar(self, sql):
        out = compose(*self._base(), '-N', '-B', '-e', sql).stdout.strip()
        return out

    def run_script(self, chunks):
        """Stream an iterator of SQL strings into a single mysql session."""
        cmd = ['docker', 'compose', *self._base()]
        proc = subprocess.Popen(cmd, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding='utf-8')
        try:
            proc.stdin.write('SET SESSION foreign_key_checks=0, unique_checks=0;\n')
            for chunk in chunks:
                proc.stdin.write(chunk)
                proc.stdin.flush()
            proc.stdin.close()
        except BrokenPipeError:
            pass
        err = proc.stderr.read()
        proc.wait()
        if proc.returncode != 0:
            sys.exit(f'mysql failed: {err}')


def q(value):
    """SQL literal for the small set of types used here."""
    if value is None:
        return 'NULL'
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, datetime):
        return "'" + value.strftime('%Y-%m-%d %H:%M:%S') + "'"
    return "'" + str(value).replace('\\', '\\\\').replace("'", "''") + "'"


def insert_batches(table, columns, rows, batch, label, total):
    """Yield multi-row INSERT IGNORE statements with progress output."""
    cols = ','.join(columns)
    buf, done, start = [], 0, time.time()
    for row in rows:
        buf.append('(' + ','.join(q(v) for v in row) + ')')
        if len(buf) >= batch:
            yield f'INSERT IGNORE INTO {table} ({cols}) VALUES {",".join(buf)};\n'
            done += len(buf)
            buf = []
            log(f'{label}: {done}/{total} rows ({done / max(time.time() - start, 1e-9):,.0f} rows/s)')
    if buf:
        yield f'INSERT IGNORE INTO {table} ({cols}) VALUES {",".join(buf)};\n'
        done += len(buf)
    log(f'{label}: {done}/{total} rows in {time.time() - start:.1f}s')


class Zipf:
    """Skewed picker over 1..n (a few hot ids, long cold tail)."""

    def __init__(self, n, s, rng):
        self.rng = rng
        total, cum = 0.0, []
        for i in range(1, n + 1):
            total += 1.0 / (i ** s)
            cum.append(total)
        self.cum, self.total = cum, total

    def pick(self):
        return bisect.bisect_left(self.cum, self.rng.random() * self.total) + 1


def compute_hash(password):
    """ONE bcrypt hash, computed inside the app image and reused for every user."""
    code = 'import sys; from app.core.security import hash_password; print(hash_password(sys.argv[1]))'
    res = compose('exec', '-T', 'app', 'python', '-c', code, password)
    return res.stdout.strip().splitlines()[-1]


def uuid_like(text):
    h = hashlib.md5(text.encode()).hexdigest()
    return f'{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--products', type=int, default=20000)
    ap.add_argument('--users', type=int, default=2000)
    ap.add_argument('--orders', type=int, default=300000)
    ap.add_argument('--categories', type=int, default=40)
    ap.add_argument('--batch', type=int, default=5000, help='rows per INSERT statement')
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--password', default='LoadTest123!', help='password of every seeded customer')
    ap.add_argument('--skip-postgres', action='store_true')
    args = ap.parse_args()
    if args.users < KNOWN_CUSTOMERS:
        sys.exit(f'--users must be >= {KNOWN_CUSTOMERS} (known load-test accounts)')

    env = read_env()
    mysql = Mysql(env.get('DATABASE_PASSWORD', ''))
    rng = random.Random(args.seed)
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    year_start = now - timedelta(days=365)
    t0 = time.time()

    def count(table):
        return int(mysql.scalar(f'SELECT COUNT(*) FROM {table}'))

    # ---- categories -------------------------------------------------------
    if count('categories') < args.categories:
        names = []
        for i in range(args.categories):
            base = CATEGORY_NAMES[i % len(CATEGORY_NAMES)]
            names.append(base if i < len(CATEGORY_NAMES) else f'{base} {i // len(CATEGORY_NAMES) + 1}')
        rows = [(i + 1, n, f'Seeded category {n}', year_start, year_start) for i, n in enumerate(names)]
        mysql.run_script(insert_batches('categories', ['id', 'name', 'description', 'created_at', 'updated_at'], rows, args.batch, 'categories', len(rows)))
    else:
        log('categories: already seeded, skipping')

    # ---- users ------------------------------------------------------------
    if count('users WHERE email LIKE "%@loadtest.example"') < args.users:
        pw_hash = compute_hash(args.password)
        log(f'users: single bcrypt hash computed ({pw_hash[:7]}...), reused for all {args.users} users')

        def user_rows():
            for i in range(1, args.users + 1):
                created = year_start + timedelta(seconds=rng.randint(0, 300 * 24 * 3600))
                yield (USER_ID_BASE + i, f'Customer {i:04d}', f'customer{i:03d}@loadtest.example' if i <= 999 else f'customer{i}@loadtest.example',
                       pw_hash, 'user', 1, created, created)
        mysql.run_script(insert_batches('users', ['id', 'name', 'email', 'password_hash', 'role', 'is_active', 'created_at', 'updated_at'], user_rows(), args.batch, 'users', args.users))
    else:
        log('users: already seeded, skipping')

    # ---- products ---------------------------------------------------------
    cat_zipf = Zipf(args.categories, 1.0, rng)
    prod_rows = []  # (id, price, name) kept in memory for the orders step
    prod_stamp = sorted(year_start + timedelta(seconds=rng.randint(0, 364 * 24 * 3600)) for _ in range(args.products))
    price_of, name_of = {}, {}
    for pid in range(1, args.products + 1):
        name = f'{rng.choice(ADJECTIVES)} {rng.choice(NOUNS)} {rng.choice(ADJECTIVES)} {pid}'
        price_of[pid] = round(rng.uniform(3, 900), 2)
        name_of[pid] = name
    cat_of = {pid: cat_zipf.pick() for pid in range(1, args.products + 1)}
    if count('products') < args.products:
        def product_rows():
            for pid in range(1, args.products + 1):
                ts = prod_stamp[pid - 1]
                desc = f'{name_of[pid]}. Seeded product for performance testing, ref {pid}.'
                image = f'/media/seed/{pid}.jpg' if pid % 10 else None
                yield (pid, cat_of[pid], name_of[pid], desc, price_of[pid], image, 1, ts, ts)
        mysql.run_script(insert_batches('products', ['id', 'category_id', 'name', 'description', 'price', 'image_url', 'is_active', 'created_at', 'updated_at'], product_rows(), args.batch, 'products', args.products))
    else:
        log('products: already seeded, skipping')

    # ---- orders + order_items --------------------------------------------
    user_zipf = Zipf(args.users, 0.8, rng)
    prod_zipf = Zipf(args.products, 0.7, rng)
    if count('orders WHERE id <= %d' % args.orders) < args.orders:
        stamps = sorted(rng.randint(0, 365 * 24 * 3600 - 1) for _ in range(args.orders))
        order_rows, item_rows = [], []
        item_id = 0
        for oid in range(1, args.orders + 1):
            ts = year_start + timedelta(seconds=stamps[oid - 1])
            n_items = rng.choices([1, 2, 3, 4, 5], weights=[10, 25, 30, 25, 10])[0]
            chosen = set()
            while len(chosen) < n_items:
                chosen.add(prod_zipf.pick())
            total = 0.0
            for pid in sorted(chosen):
                qty = rng.choice([1, 1, 1, 2, 2, 3])
                sub = round(price_of[pid] * qty, 2)
                total += sub
                item_id += 1
                item_rows.append((item_id, oid, pid, name_of[pid], qty, price_of[pid], sub))
            age_days = (now - ts).days
            status = 'delivered' if age_days > 45 and rng.random() < 0.8 else rng.choices(STATUSES, weights=STATUS_WEIGHTS)[0]
            order_rows.append((oid, USER_ID_BASE + user_zipf.pick(), round(total, 2), status, uuid_like(f'seed-order-{oid}'), ts, ts))
        log(f'orders: generated {len(order_rows)} orders and {len(item_rows)} items in memory')
        mysql.run_script(insert_batches('orders', ['id', 'user_id', 'total_amount', 'status', 'reservation_id', 'created_at', 'updated_at'], order_rows, args.batch, 'orders', len(order_rows)))
        mysql.run_script(insert_batches('order_items', ['id', 'order_id', 'product_id', 'product_name', 'quantity', 'unit_price', 'subtotal'], item_rows, args.batch, 'order_items', len(item_rows)))
    else:
        log('orders: already seeded, skipping')

    mysql.run_script(['ANALYZE TABLE users, categories, products, orders, order_items;\n'])
    log('ANALYZE TABLE done (fresh optimizer statistics)')

    # ---- postgres stock: one row for EVERY product id in MySQL ------------
    if not args.skip_postgres:
        ids = [int(x) for x in mysql.scalar('SELECT id FROM products ORDER BY id').split()]
        stock_rng = random.Random(args.seed + 1)
        lines = ''.join(f'{pid}\t{stock_rng.randint(20000, 50000)}\n' for pid in ids)
        script = ('CREATE TEMP TABLE seed_stock(product_id BIGINT, available INT);\n'
                  'COPY seed_stock FROM STDIN;\n' + lines + '\\.\n'
                  'INSERT INTO inventory(product_id, available) SELECT product_id, available FROM seed_stock ON CONFLICT (product_id) DO NOTHING;\n'
                  'ANALYZE inventory;\n')
        t1 = time.time()
        compose('exec', '-T', 'inventory-db', 'psql', '-U', 'inventory', '-d', 'inventory', '-v', 'ON_ERROR_STOP=1', stdin=script)
        n_pg = compose('exec', '-T', 'inventory-db', 'psql', '-U', 'inventory', '-d', 'inventory', '-tA', '-c', 'SELECT COUNT(*) FROM inventory').stdout.strip()
        log(f'postgres: {len(ids)} MySQL product ids -> inventory now has {n_pg} rows ({time.time() - t1:.1f}s)')
        if int(n_pg) < len(ids):
            sys.exit('inventory has fewer rows than products')

    summary = {t: count(t) for t in ('users', 'categories', 'products', 'orders', 'order_items')}
    log(f'DONE in {time.time() - t0:.1f}s: {summary}')


if __name__ == '__main__':
    main()

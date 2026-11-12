"""Req 3 migration 002 (SEPARATE from the additive startup migration): drop the two single-column indexes that the composite
indexes made redundant, with a working downgrade.

  products.idx_category_id (category_id)   covered by idx_products_cat_active_created (category_id, is_active, created_at, id)
  orders.idx_orders_user_id (user_id)      covered by idx_orders_user_created (user_id, created_at, id)

Any query that could use the single-column index can use the leading column of the composite one, so nothing gets slower,
while every INSERT/UPDATE/DELETE maintains one B-tree less (the answer to "what slows an index down?") and the buffer pool holds less.
The foreign keys (fk_products_category_id, fk_orders_user_id) need an index whose FIRST column is the FK column: the composite
indexes provide it, and `upgrade` verifies that before dropping anything.

Run explicitly (never automatically at application start):
  docker compose run --rm --no-deps app python -m app.core.migrations_req3_indexes up|down|status
"""
import sys
from sqlalchemy import inspect, text
from app.core.database import engine

VERSION = 'req3_002_drop_redundant_indexes'
# (table, redundant index, its column, composite index that covers it)
REDUNDANT = [
    ('products', 'idx_category_id', 'category_id', 'idx_products_cat_active_created'),
    ('orders', 'idx_orders_user_id', 'user_id', 'idx_orders_user_created'),
]


def _indexes(conn, table):
    return {i['name']: i['column_names'] for i in inspect(conn).get_indexes(table)}


def _record(conn, applied):
    conn.execute(text('CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR(100) PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)'))
    if applied:
        conn.execute(text('INSERT IGNORE INTO schema_migrations (version) VALUES (:v)'), {'v': VERSION})
    else:
        conn.execute(text('DELETE FROM schema_migrations WHERE version=:v'), {'v': VERSION})


def upgrade():
    with engine.begin() as conn:
        for table, name, column, covering in REDUNDANT:
            idx = _indexes(conn, table)
            if name not in idx:
                continue
            if covering not in idx or idx[covering][0] != column:
                raise RuntimeError(f'refusing to drop {name}: {covering} does not lead with {column} (the foreign key would lose its index)')
            conn.execute(text(f'DROP INDEX {name} ON {table}'))
            print(f'dropped {table}.{name} (covered by {covering})')
        _record(conn, True)


def downgrade():
    with engine.begin() as conn:
        for table, name, column, _ in REDUNDANT:
            if name not in _indexes(conn, table):
                conn.execute(text(f'CREATE INDEX {name} ON {table} ({column})'))
                print(f'recreated {table}.{name}')
        _record(conn, False)


def status():
    with engine.connect() as conn:
        for table, name, _, covering in REDUNDANT:
            idx = _indexes(conn, table)
            print(f'{table}: {name}={"present" if name in idx else "absent"}  {covering}={"present" if covering in idx else "absent"}')


if __name__ == '__main__':
    {'up': upgrade, 'down': downgrade, 'status': status}.get(sys.argv[1] if len(sys.argv) > 1 else 'status', status)()

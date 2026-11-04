"""Idempotent additive migration for the original course schema."""
import logging
from sqlalchemy import inspect, text
from app.core.database import Base, engine
import app.core.model_registry  # registers tables

log=logging.getLogger(__name__)
log.setLevel(logging.INFO)
if not log.handlers:
    handler=logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(levelname)s:%(name)s:%(message)s'))
    log.addHandler(handler)
log.propagate=False
ADDITIONS={
    'users':{'is_active':"BOOLEAN NOT NULL DEFAULT 1"},
    'products':{'is_active':"BOOLEAN NOT NULL DEFAULT 1"},
    'orders':{'reservation_id':"VARCHAR(36) NULL"},
    'order_items':{'product_name':"VARCHAR(200) NULL"},
}

def migrate():
    with engine.begin() as connection:
        known=set(inspect(connection).get_table_names())
        for table, additions in ADDITIONS.items():
            if table not in known:continue
            columns={c['name'] for c in inspect(connection).get_columns(table)}
            for column, definition in additions.items():
                if column not in columns:
                    connection.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {definition}'))
                    log.info('Added %s.%s',table,column)
        if 'users' in known:
            connection.execute(text("UPDATE users SET role='user' WHERE role='customer'"))
        if 'orders' in known and engine.dialect.name=='mysql':
            indexes=inspect(connection).get_indexes('orders')
            if not any('reservation_id' in index['column_names'] for index in indexes):
                connection.execute(text('CREATE UNIQUE INDEX uq_orders_reservation_id ON orders (reservation_id)'))
                log.info('Added unique index on orders.reservation_id')
        if 'orders' in known:
            for old,new in [('Pending','pending'),('Confirmed','confirmed'),('Preparing','shipped'),('Delivered','delivered'),('Cancelled','cancelled')]:
                connection.execute(text('UPDATE orders SET status=:new WHERE status=:old'),{'old':old,'new':new})
        if 'order_items' in known and 'products' in known:
            if engine.dialect.name=='mysql':
                connection.execute(text('UPDATE order_items i JOIN products p ON p.id=i.product_id SET i.product_name=p.name WHERE i.product_name IS NULL'))
            else:
                connection.execute(text('UPDATE order_items SET product_name=(SELECT name FROM products WHERE products.id=order_items.product_id) WHERE product_name IS NULL'))
    Base.metadata.create_all(bind=engine)
    if engine.dialect.name=='mysql':
        with engine.begin() as connection:
            columns={c['name']:c for c in inspect(connection).get_columns('notifications')}
            if 'DATETIME' in str(columns['created_at']['type']).upper():
                connection.execute(text('ALTER TABLE notifications MODIFY created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP'))
                log.info('Updated notifications.created_at to MySQL TIMESTAMP')
    log.info('Ensured notifications and revoked_tokens tables exist')

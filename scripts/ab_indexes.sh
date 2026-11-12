#!/usr/bin/env bash
# Interleaved A/B/B/A measurement of the Req 3 performance indexes (A = indexes dropped, B = present).
# Drift on a laptop is larger than the effect we measure, so both conditions are run in the same window.
# Leaves the indexes CREATED when it finishes.
cd "$(dirname "$0")/.."
sql(){ docker compose exec -T db sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" ecommerce 2>/dev/null' <<<"$1"; }
drop(){ sql "DROP INDEX idx_products_active_created ON products; DROP INDEX idx_products_cat_active_created ON products; DROP INDEX idx_orders_user_created ON orders;"; }
make(){ sql "CREATE INDEX idx_products_active_created ON products (is_active, created_at, id); CREATE INDEX idx_products_cat_active_created ON products (category_id, is_active, created_at, id); CREATE INDEX idx_orders_user_created ON orders (user_id, created_at, id);"; }
trap make EXIT   # restore the indexes when the script ends (it must not be killed mid-run)
for o in "$@"; do
  i=0
  for cond in A B B A; do
    i=$((i+1)); [ $cond = A ] && drop || { sql "show index from orders" | grep -q idx_orders_user_created || make; }
    label=ab_idx_${o}_${i}${cond}
    py scripts/bench.py --label $label --only $o >/dev/null 2>&1
    echo "$label orders=$(sql 'select count(*) from orders' | tail -1)"
  done
done

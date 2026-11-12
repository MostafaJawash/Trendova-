#!/bin/sh
# One-shot replica initialisation (idempotent). Runs in a throw-away mysql:8.0 container on the compose network.
#  1. If replication already runs -> nothing to do.
#  2. Create a replication user on the primary.
#  3. Take a consistent dump of the primary (--single-transaction, GTID_PURGED included) and load it into the replica.
#  4. CHANGE REPLICATION SOURCE TO ... SOURCE_AUTO_POSITION=1, GET_SOURCE_PUBLIC_KEY=1; START REPLICA.
#  5. SET PERSIST read_only / super_read_only = ON (persisted across restarts).
set -eu
DB="${DATABASE_NAME:-ecommerce}"
P="mysql -h db -uroot -p$MYSQL_ROOT_PASSWORD"
R="mysql -h db-replica -uroot -p$MYSQL_ROOT_PASSWORD"
for i in $(seq 1 60); do $R -e 'SELECT 1' >/dev/null 2>&1 && break; sleep 2; done
STATUS=$($R -e 'SHOW REPLICA STATUS\G' 2>/dev/null || true)
if echo "$STATUS" | grep -q 'Replica_IO_Running: Yes' && echo "$STATUS" | grep -q 'Replica_SQL_Running: Yes'; then
  $R -e 'SET PERSIST read_only=ON; SET PERSIST super_read_only=ON' 2>/dev/null
  echo 'replica-init: replication already running, nothing to do'; exit 0
fi
echo 'replica-init: creating replication user on the primary'
$P -e "CREATE USER IF NOT EXISTS 'repl'@'%' IDENTIFIED BY '$MYSQL_ROOT_PASSWORD'; GRANT REPLICATION SLAVE ON *.* TO 'repl'@'%';" 2>/dev/null
echo 'replica-init: loading a consistent dump (single transaction, GTID info)'
$R -e 'STOP REPLICA; RESET REPLICA ALL; SET GLOBAL super_read_only=OFF; SET GLOBAL read_only=OFF; RESET MASTER' 2>/dev/null || true
mysqldump -h db -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction --set-gtid-purged=ON --routines --triggers \
  --no-tablespaces --databases "$DB" 2>/dev/null | $R
echo 'replica-init: starting replication'
$R -e "CHANGE REPLICATION SOURCE TO SOURCE_HOST='db', SOURCE_PORT=3306, SOURCE_USER='repl', SOURCE_PASSWORD='$MYSQL_ROOT_PASSWORD', SOURCE_AUTO_POSITION=1, GET_SOURCE_PUBLIC_KEY=1; START REPLICA;" 2>/dev/null
for i in $(seq 1 30); do
  S=$($R -e 'SHOW REPLICA STATUS\G' 2>/dev/null)
  echo "$S" | grep -q 'Replica_IO_Running: Yes' && echo "$S" | grep -q 'Replica_SQL_Running: Yes' && break
  sleep 2
done
$R -e 'SET PERSIST read_only=ON; SET PERSIST super_read_only=ON' 2>/dev/null
$R -e 'SHOW REPLICA STATUS\G' 2>/dev/null | grep -E 'Replica_IO_Running|Replica_SQL_Running|Seconds_Behind|Last_.*Error:' 
echo 'replica-init: done'

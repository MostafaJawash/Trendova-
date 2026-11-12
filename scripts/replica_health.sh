#!/bin/sh
# db-replica healthcheck: healthy only while both replication threads run and the replica is read-only.
S=$(mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "SHOW REPLICA STATUS\G" 2>/dev/null)
echo "$S" | grep -q "Replica_IO_Running: Yes" || exit 1
echo "$S" | grep -q "Replica_SQL_Running: Yes" || exit 1
[ "$(mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -Nse 'SELECT @@super_read_only' 2>/dev/null)" = "1" ] || exit 1
exit 0

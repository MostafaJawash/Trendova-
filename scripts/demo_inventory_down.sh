#!/usr/bin/env sh
set -eu
docker compose stop inventory-service
echo 'Warehouse stopped: POST /orders returns 503 INVENTORY_UNAVAILABLE; GET /products/{id} remains 200 with stock.status unavailable.'
docker compose start inventory-service
echo 'Warehouse restarted; the application reconnects without restart.'

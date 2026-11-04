#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
rm -rf inventory-service/gen
mkdir -p inventory-service/gen/inventoryv1
protoc -I proto --go_out=inventory-service --go_opt=paths=source_relative --go-grpc_out=inventory-service --go-grpc_opt=paths=source_relative proto/inventory.proto
mv inventory-service/inventory.pb.go inventory-service/inventory_grpc.pb.go inventory-service/gen/inventoryv1/

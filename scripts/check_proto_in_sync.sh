#!/usr/bin/env sh
set -eu
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
protoc -I proto --go_out="$tmp" --go_opt=paths=source_relative --go-grpc_out="$tmp" --go-grpc_opt=paths=source_relative proto/inventory.proto
mkdir -p "$tmp/gen/inventoryv1"
mv "$tmp/inventory.pb.go" "$tmp/inventory_grpc.pb.go" "$tmp/gen/inventoryv1/"
diff -ru inventory-service/gen "$tmp/gen"

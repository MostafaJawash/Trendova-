$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
Remove-Item -Recurse -Force inventory-service/gen -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force inventory-service/gen/inventoryv1 | Out-Null
protoc -I proto --go_out=inventory-service --go_opt=paths=source_relative --go-grpc_out=inventory-service --go-grpc_opt=paths=source_relative proto/inventory.proto
Move-Item inventory-service/inventory.pb.go, inventory-service/inventory_grpc.pb.go inventory-service/gen/inventoryv1/

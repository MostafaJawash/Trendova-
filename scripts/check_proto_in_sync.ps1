$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
$tmp = Join-Path ([IO.Path]::GetTempPath()) ('trendova-proto-' + [guid]::NewGuid())
try {
  New-Item -ItemType Directory -Force "$tmp/gen/inventoryv1" | Out-Null
  protoc -I proto "--go_out=$tmp" --go_opt=paths=source_relative "--go-grpc_out=$tmp" --go-grpc_opt=paths=source_relative proto/inventory.proto
  Move-Item "$tmp/inventory.pb.go", "$tmp/inventory_grpc.pb.go" "$tmp/gen/inventoryv1/"
  $diff = Compare-Object (Get-Content -Raw inventory-service/gen/inventoryv1/inventory.pb.go),(Get-Content -Raw "$tmp/gen/inventoryv1/inventory.pb.go")
  $diff += Compare-Object (Get-Content -Raw inventory-service/gen/inventoryv1/inventory_grpc.pb.go),(Get-Content -Raw "$tmp/gen/inventoryv1/inventory_grpc.pb.go")
  if ($diff) { throw 'Committed Go protobuf sources are stale; run scripts/gen_proto_go.ps1.' }
} finally { Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue }

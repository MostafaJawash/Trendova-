$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force app/integrations/inventory/generated | Out-Null
python -m grpc_tools.protoc -I proto --python_out=app/integrations/inventory/generated --grpc_python_out=app/integrations/inventory/generated proto/inventory.proto
$path = 'app/integrations/inventory/generated/inventory_pb2_grpc.py'
(Get-Content -Raw $path).Replace('import inventory_pb2 as inventory__pb2', 'from . import inventory_pb2 as inventory__pb2') | Set-Content -NoNewline $path
New-Item -ItemType File -Force app/integrations/inventory/generated/__init__.py | Out-Null

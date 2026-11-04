#!/usr/bin/env sh
set -eu
mkdir -p app/integrations/inventory/generated
python -m grpc_tools.protoc -I proto --python_out=app/integrations/inventory/generated --grpc_python_out=app/integrations/inventory/generated proto/inventory.proto
python - <<'PY'
from pathlib import Path
p = Path('app/integrations/inventory/generated/inventory_pb2_grpc.py')
p.write_text(p.read_text().replace('import inventory_pb2 as inventory__pb2', 'from . import inventory_pb2 as inventory__pb2'))
Path('app/integrations/inventory/generated/__init__.py').touch()
PY

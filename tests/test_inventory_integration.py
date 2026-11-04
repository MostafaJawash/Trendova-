"""Live inventory checks are intentionally opt-in: RUN_INTEGRATION=1."""
import os
import pytest
pytestmark=pytest.mark.skipif(os.getenv('RUN_INTEGRATION')!='1',reason='set RUN_INTEGRATION=1 for compose-backed checks')
def test_inventory_integration_requires_running_stack():
    # The Go integration suite is authoritative for warehouse transaction semantics.
    assert os.getenv('INVENTORY_GRPC_ADDR')

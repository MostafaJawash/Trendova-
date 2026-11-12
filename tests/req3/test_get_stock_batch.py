"""GetStockBatch (Requirement 3, cross-service N+1) against the REAL Go inventory service.

Needs the compose stack (E2E_BASE_URL set, run in the `tester` container). Product ids >= 9_000_000_000 are used for the
throw-away stock rows so they can never collide with seeded products; they are deleted again at the end.
"""
import os
import random
import time
import pytest
from tests.req3 import live

pytestmark = [pytest.mark.req3_phase1, pytest.mark.skipif(not live.BASE, reason='E2E_BASE_URL not set (needs the compose stack)')]
ADDR = os.getenv('INVENTORY_GRPC_ADDR', 'inventory-service:50051')


@pytest.fixture(scope='module')
def gw():
    from app.integrations.inventory.gateway import GrpcInventoryGateway
    g = GrpcInventoryGateway(address=ADDR)
    yield g
    g.close()


@pytest.fixture
def ids(gw):
    base = 9_000_000_000 + random.randint(0, 10**8) * 1000
    made = [base + i for i in range(1, 8)]
    for n, pid in enumerate(made):
        gw.set_stock(pid, 10 + n)
    yield made
    live.docker('exec', live.cname('inventory-db'), 'psql', '-U', 'inventory', '-d', 'inventory', '-c',
                f'DELETE FROM inventory WHERE product_id >= 9000000000', check=False)


def test_batch_equals_n_single_calls(gw, ids):
    batch = gw.get_quantities(ids)
    single = {pid: gw.get_quantity(pid) for pid in ids}
    assert batch == single and len(batch) == len(ids)


def test_one_rpc_instead_of_n(gw, ids):
    from app.integrations.inventory import gateway as g
    box = g.start_rpc_count(); gw.get_quantities(ids)
    assert box[0] == 1
    box = g.start_rpc_count(); gw.get_quantities_naive(ids)
    assert box[0] == len(ids)


def test_empty_list_returns_empty(gw):
    assert gw.get_quantities([]) == {}


def test_unknown_id_is_defined_behaviour(gw, ids):
    from app.integrations.inventory.generated import inventory_pb2
    unknown = ids[-1] + 5000
    assert gw.get_quantities([ids[0], unknown])[unknown] == 0               # same answer as the single call
    r = gw.stub.GetStockBatch(inventory_pb2.GetStockBatchRequest(product_ids=[ids[0], unknown]), timeout=2)
    assert [(i.product_id, i.found) for i in r.items] == [(ids[0], True), (unknown, False)]   # but the raw RPC says "not found"


def test_duplicates_collapse_and_order_is_first_seen(gw, ids):
    from app.integrations.inventory.generated import inventory_pb2
    r = gw.stub.GetStockBatch(inventory_pb2.GetStockBatchRequest(product_ids=[ids[2], ids[0], ids[2]]), timeout=2)
    assert [i.product_id for i in r.items] == [ids[2], ids[0]]


def test_max_batch_size_guard(gw):
    import grpc
    from app.integrations.inventory.generated import inventory_pb2
    ok = gw.stub.GetStockBatch(inventory_pb2.GetStockBatchRequest(product_ids=list(range(1, 501))), timeout=5)
    assert len(ok.items) == 500
    with pytest.raises(grpc.RpcError) as e:
        gw.stub.GetStockBatch(inventory_pb2.GetStockBatchRequest(product_ids=list(range(1, 502))), timeout=5)
    assert e.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_client_chunks_large_requests(gw):
    from app.integrations.inventory import gateway as g
    box = g.start_rpc_count()
    out = gw.get_quantities(list(range(1, 451)))      # inventory_batch_max=200 -> 3 calls
    assert len(out) == 450 and box[0] == 3


def test_invalid_id_rejected(gw):
    import grpc
    from app.integrations.inventory.generated import inventory_pb2
    with pytest.raises(grpc.RpcError) as e:
        gw.stub.GetStockBatch(inventory_pb2.GetStockBatchRequest(product_ids=[-5]), timeout=2)
    assert e.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_inventory_service_down_same_failure_behaviour_and_restored(gw, ids):
    """Single call and batch fail the same way (InventoryUnavailableError within the 2 s deadline); the API still answers 200
    with stock status 'unavailable'. The service is started again afterwards."""
    from app.integrations.inventory.gateway import InventoryUnavailableError
    api = live.Api(); admin = api.admin()
    pid, _ = api.new_product(admin, quantity=3)
    _, user = api.new_user()
    with live.container_stopped('inventory-service'):
        t = time.time()
        with pytest.raises(InventoryUnavailableError):
            gw.get_quantity(ids[0])
        with pytest.raises(InventoryUnavailableError):
            gw.get_quantities(ids)
        assert time.time() - t < 6
        r = api.c.get(f'/products?include_stock=true&limit=5', headers=user)
        assert r.status_code == 200
        assert all(i['stock'] == {'quantity': None, 'status': 'unavailable'} for i in r.json()['items'])
    assert gw.get_quantities(ids) == {pid_: 10 + n for n, pid_ in enumerate(ids)}    # recovered after the restart


def test_include_stock_is_opt_in_and_matches_detail(gw):
    api = live.Api(); admin = api.admin()
    pid, cat = api.new_product(admin, quantity=7)
    _, user = api.new_user()
    plain = api.c.get(f'/products?category={cat}', headers=user).json()['items'][0]
    assert 'stock' not in plain                                   # default off: response unchanged
    withs = api.c.get(f'/products?category={cat}&include_stock=true', headers=user).json()['items'][0]
    assert withs['stock'] == {'quantity': 7, 'status': 'available'}
    assert api.c.get(f'/products/{pid}', headers=user).json()['stock'] == withs['stock']

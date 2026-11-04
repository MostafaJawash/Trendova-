import logging
import grpc
import pytest
from app.integrations.inventory.gateway import GrpcInventoryGateway, InventoryUnavailableError, ReserveResult

class RpcFailure(grpc.RpcError):
    def __init__(self, code): self._code=code
    def code(self): return self._code

class Stub:
    def __init__(self, reserve=None, release=None): self.reserve=reserve;self.release=release;self.release_calls=[]
    def Reserve(self, request, timeout):
        if isinstance(self.reserve,Exception): raise self.reserve
        return self.reserve
    def Release(self, request, timeout):
        self.release_calls.append((request,timeout))
        if isinstance(self.release,Exception): raise self.release
        return self.release or {'released':True}

@pytest.mark.parametrize('code',[grpc.StatusCode.UNAVAILABLE,grpc.StatusCode.DEADLINE_EXCEEDED])
def test_transport_errors_become_inventory_unavailable(code):
    gateway=GrpcInventoryGateway(stub=Stub(reserve=RpcFailure(code)))
    with pytest.raises(InventoryUnavailableError): gateway.reserve('r1',[{'product_id':1,'quantity':1}])

def test_reserve_shortages_are_mapped():
    gateway=GrpcInventoryGateway(stub=Stub(reserve={'success':False,'shortages':[{'product_id':3,'requested':2,'available':1}]}))
    assert gateway.reserve('r2',[{'product_id':3,'quantity':2}]) == ReserveResult(False,[{'product_id':3,'requested':2,'available':1}])

def test_reserve_timeout_attempts_best_effort_release():
    stub=Stub(reserve=RpcFailure(grpc.StatusCode.DEADLINE_EXCEEDED))
    with pytest.raises(InventoryUnavailableError): GrpcInventoryGateway(stub=stub,timeout=.1).reserve('r3',[{'product_id':1,'quantity':1}])
    assert len(stub.release_calls)==1 and stub.release_calls[0][0]['reservation_id']=='r3'

def test_release_retries_three_times_and_logs(caplog):
    stub=Stub(release=RpcFailure(grpc.StatusCode.UNAVAILABLE))
    with caplog.at_level(logging.ERROR),pytest.raises(InventoryUnavailableError): GrpcInventoryGateway(stub=stub,timeout=.01).release('r4')
    assert len(stub.release_calls)==3
    assert 'Failed releasing reservation r4 after 3 attempts' in caplog.text

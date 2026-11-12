"""Inventory boundary: production uses gRPC; unit tests use the fake."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
import logging, time
from threading import RLock
from app.core.config import settings
log = logging.getLogger(__name__)
class InventoryUnavailableError(Exception): pass
from contextvars import ContextVar
_rpc_calls:ContextVar=ContextVar('inventory_rpc_calls',default=None)  # per-request gRPC call counter (diagnostics)
def start_rpc_count():
 box=[0];_rpc_calls.set(box);return box
def _count_rpc():
 box=_rpc_calls.get()
 if box is not None:box[0]+=1
@dataclass
class ReserveResult: success: bool; shortages: list
class InventoryGateway(ABC):
 @abstractmethod
 def get_quantity(self, product_id): ...
 @abstractmethod
 def reserve(self, reservation_id, items): ...
 @abstractmethod
 def release(self, reservation_id): ...
 @abstractmethod
 def set_stock(self, product_id, quantity): ...
 def get_quantities(self, product_ids):
  """{product_id: quantity} for many ids. Default = N single calls; the gRPC gateway overrides it with ONE call."""
  return self.get_quantities_naive(product_ids)
 def get_quantities_naive(self, product_ids):
  """Per-item path (N calls). Kept ONLY as the benchmark/test variant of get_quantities."""
  return {int(i):self.get_quantity(i) for i in dict.fromkeys(int(x) for x in product_ids)}
class FakeInventoryGateway(InventoryGateway):
 def __init__(self): self.stock={}; self.reservations={}; self.lock=RLock()
 def get_quantity(self, product_id):
  with self.lock:return self.stock.get(int(product_id),0)
 def set_stock(self, product_id, quantity):
  with self.lock:self.stock[int(product_id)]=int(quantity)
 def reserve(self, reservation_id, items):
  with self.lock:
   if reservation_id in self.reservations:return ReserveResult(True,[])
   merged={}
   for x in items: merged[int(x['product_id'])]=merged.get(int(x['product_id']),0)+int(x['quantity'])
   shortages=[{'product_id':p,'requested':q,'available':self.stock.get(p,0)} for p,q in merged.items() if self.stock.get(p,0)<q]
   if shortages:return ReserveResult(False,shortages)
   self.reservations[reservation_id]=list(merged.items())
   for p,q in self.reservations[reservation_id]:self.stock[p]-=q
   return ReserveResult(True,[])
 def release(self, reservation_id):
  with self.lock:
   for p,q in self.reservations.pop(reservation_id,[]):self.stock[p]=self.stock.get(p,0)+q
class GrpcInventoryGateway(InventoryGateway):
 """Sync client, appropriate for the application's synchronous route handlers."""
 def __init__(self,address=None,timeout=None,stub=None,channel=None):
  self.timeout=float(timeout if timeout is not None else settings.inventory_timeout_seconds);self.channel=channel
  if stub is not None:self.stub=stub;self.pb2=None
  else:
   import grpc
   from app.integrations.inventory.generated import inventory_pb2,inventory_pb2_grpc
   self.pb2=inventory_pb2;self.channel=channel or grpc.insecure_channel(address or settings.inventory_grpc_addr);self.stub=inventory_pb2_grpc.InventoryServiceStub(self.channel)
 def _request(self,name,**kwargs):return kwargs if self.pb2 is None else getattr(self.pb2,name)(**kwargs)
 def _rpc(self,call,request,timeout=None):
  _count_rpc()
  try:return call(request,timeout=self.timeout if timeout is None else timeout)
  except Exception as exc:
   code=getattr(exc,'code',lambda:None)()
   try:
    import grpc
    transport=code in (grpc.StatusCode.UNAVAILABLE,grpc.StatusCode.DEADLINE_EXCEEDED)
   except ImportError:transport=code is not None
   if transport or code is not None:raise InventoryUnavailableError('Warehouse request failed') from exc
   raise
 def get_quantity(self,product_id):
  r=self._rpc(self.stub.GetQuantity,self._request('GetQuantityRequest',product_id=int(product_id)))
  return int(getattr(r,'available',r.get('available',0) if isinstance(r,dict) else 0))
 def get_quantities(self,product_ids):
  """ONE GetStockBatch call per <=inventory_batch_max ids (same 2 s deadline / error mapping as the single call)."""
  ids=list(dict.fromkeys(int(x) for x in product_ids));out={}
  for i in range(0,len(ids),settings.inventory_batch_max):
   chunk=ids[i:i+settings.inventory_batch_max]
   r=self._rpc(self.stub.GetStockBatch,self._request('GetStockBatchRequest',product_ids=chunk))
   items=getattr(r,'items',None) if self.pb2 is not None else r.get('items',[])
   for it in items:
    pid=int(it['product_id'] if isinstance(it,dict) else it.product_id);av=int(it['available'] if isinstance(it,dict) else it.available);out[pid]=av
   for pid in chunk:out.setdefault(pid,0)  # unknown id -> 0, like the single call
  return out
 def reserve(self,reservation_id,items):
  request=self._request('ReserveRequest',reservation_id=reservation_id,items=items) if self.pb2 is None else self.pb2.ReserveRequest(reservation_id=reservation_id,items=[self.pb2.ReserveItem(product_id=int(x['product_id']),quantity=int(x['quantity'])) for x in items])
  try:r=self._rpc(self.stub.Reserve,request)
  except InventoryUnavailableError:self._best_effort_release(reservation_id);raise
  success=getattr(r,'success',r.get('success') if isinstance(r,dict) else False);shortages=getattr(r,'shortages',r.get('shortages',[]) if isinstance(r,dict) else [])
  def shortage(s):
   if isinstance(s,dict):return {'product_id':int(s['product_id']),'requested':int(s['requested']),'available':int(s['available'])}
   return {'product_id':int(s.product_id),'requested':int(s.requested),'available':int(s.available)}
  return ReserveResult(bool(success),[shortage(s) for s in shortages])
 def _best_effort_release(self,reservation_id):
  try:self._rpc(self.stub.Release,self._request('ReleaseRequest',reservation_id=reservation_id),min(self.timeout,.5))
  except Exception:log.error('Best-effort release failed for reservation %s',reservation_id)
 def release(self,reservation_id):
  last=None
  for attempt in range(3):
   try:self._rpc(self.stub.Release,self._request('ReleaseRequest',reservation_id=reservation_id),min(self.timeout,.75));return
   except InventoryUnavailableError as exc:
    last=exc
    if attempt<2:time.sleep(.05*(attempt+1))
  log.error('Failed releasing reservation %s after 3 attempts',reservation_id);raise last
 def set_stock(self,product_id,quantity):
  r=self._rpc(self.stub.SetStock,self._request('SetStockRequest',product_id=int(product_id),quantity=int(quantity)))
  return int(getattr(r,'available',r.get('available',quantity) if isinstance(r,dict) else quantity))
 def close(self):
  if self.channel is not None:self.channel.close()
gateway:InventoryGateway=FakeInventoryGateway()
def configure_gateway():
 global gateway
 if settings.inventory_mode=='fake':return gateway
 if settings.inventory_mode!='grpc':raise ValueError('INVENTORY_MODE must be fake or grpc')
 gateway=GrpcInventoryGateway();return gateway
def close_gateway():
 close=getattr(gateway,'close',None)
 if close:close()

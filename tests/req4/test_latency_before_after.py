"""Live Req4 latency benchmark. Run inside tester with REQ4_QUICK=1 for eight samples."""
import json, os, statistics, time
from datetime import datetime
from pathlib import Path
import httpx, pytest
from tests.req3.live import Api

pytestmark=pytest.mark.req4_latency
N=8 if os.getenv('REQ4_QUICK')=='1' else 20
AFTER=os.getenv('REQ4_AFTER_URL','http://app:8000/api/v1')
BEFORE=os.getenv('REQ4_BEFORE_URL','http://app-inline:8000/api/v1')

def percentile(values,p):
    values=sorted(values); return values[min(len(values)-1,round((len(values)-1)*p))]
def summary(values):
    return {key:round(value,2) for key,value in {'p50':percentile(values,.5),'p95':percentile(values,.95),'p99':percentile(values,.99),'max':max(values)}.items()}
def login(url):
    response=httpx.post(url+'/auth/login',json={'email':os.getenv('E2E_ADMIN_EMAIL','admin@example.com'),'password':os.getenv('E2E_ADMIN_PASSWORD','ChangeMe123!')},timeout=20); response.raise_for_status(); return {'Authorization':'Bearer '+response.json()['access_token']}
def create(url,headers,product_id):
    started=time.perf_counter(); response=httpx.post(url+'/orders',headers=headers,json={'items':[{'product_id':product_id,'quantity':1}]},timeout=30); return response.status_code,(time.perf_counter()-started)*1000

def test_latency_before_after_interleaved():
    """Normal SMTP scenario; run compose with --profile req4 so app-inline is reachable."""
    api=Api(); admin=api.admin(); product,_=api.new_product(admin,quantity=N*4)
    before_h=login(BEFORE); after_h=login(AFTER)
    create(BEFORE,before_h,product); create(AFTER,after_h,product)  # warm-up
    before=[]; after=[]
    for _ in range(N):
        status,value=create(BEFORE,before_h,product); assert status==201; before.append(value)
        status,value=create(AFTER,after_h,product); assert status==201; after.append(value)
    b,a=summary(before),summary(after); factor=round(b['p50']/a['p50'],2) if a['p50'] else None
    print(f"SCENARIO a: normal SMTP      BEFORE(inline) p50={b['p50']}ms p95={b['p95']}ms p99={b['p99']}ms | AFTER(queue) p50={a['p50']}ms p95={a['p95']}ms p99={a['p99']}ms | factor={factor}x")
    result={'scenario':'normal_smtp','samples':N,'before':b,'after':a,'factor':factor,'measured_at':datetime.now().isoformat()}
    target=Path('/app/loadtest/results'); target.mkdir(parents=True,exist_ok=True)
    (target/f"req4_latency_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json").write_text(json.dumps(result,indent=2))

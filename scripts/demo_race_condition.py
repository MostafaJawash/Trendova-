"""Create twenty simultaneous orders for one last unit and print a PASS/FAIL result."""
import os, threading
import httpx as requests
base=os.getenv('API_URL','http://localhost:8000/api/v1'); password=os.getenv('ADMIN_PASSWORD','ChangeMe123!')
def login(email,password):
 r=requests.post(base+'/auth/login',json={'email':email,'password':password});r.raise_for_status();return {'Authorization':'Bearer '+r.json()['access_token']}
admin=login('admin@example.com',password)
r=requests.post(base+'/categories',json={'name':'Race demo'},headers=admin)
if r.status_code==409: category=next(x['id'] for x in requests.get(base+'/categories',headers=admin).json()['items'] if x['name']=='Race demo')
else:r.raise_for_status();category=r.json()['id']
r=requests.post(base+'/products',data={'name':'Last unit '+os.urandom(4).hex(),'price':'1.00','category_id':category,'initial_quantity':1},headers=admin);r.raise_for_status();product=r.json()['id']
headers=[]
for i in range(20):
 email=f'race-{product}-{i}@example.com';requests.post(base+'/auth/register',json={'email':email,'name':'Race','password':'password123'});headers.append(login(email,'password123'))
barrier=threading.Barrier(20);results=[];lock=threading.Lock()
def order(h):
 barrier.wait();r=requests.post(base+'/orders',json={'items':[{'product_id':product,'quantity':1}]},headers=h)
 with lock:results.append(r.status_code)
threads=[threading.Thread(target=order,args=(h,)) for h in headers]
[t.start() for t in threads];[t.join() for t in threads]
stock=requests.get(base+f'/products/{product}',headers=admin).json()['stock']['quantity'];ok=results.count(201)==1 and results.count(409)==19 and stock==0
print(f"{'PASS' if ok else 'FAIL'} | 201={results.count(201)} | 409={results.count(409)} | stock={stock}")
raise SystemExit(0 if ok else 1)

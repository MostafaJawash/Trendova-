"""Idempotently seed the running HTTP API. Set API_URL and ADMIN_PASSWORD if needed."""
import os
import httpx as requests
base=os.getenv('API_URL','http://localhost:8000/api/v1'); password=os.getenv('ADMIN_PASSWORD','ChangeMe123!')
r=requests.post(base+'/auth/login',json={'email':'admin@example.com','password':password});r.raise_for_status();h={'Authorization':'Bearer '+r.json()['access_token']}
categories={}
for name in ('Electronics','Home','Books'):
 r=requests.post(base+'/categories',json={'name':name},headers=h)
 if r.status_code==409:
  categories[name]=next(x['id'] for x in requests.get(base+'/categories',headers=h).json()['items'] if x['name']==name)
 else:r.raise_for_status();categories[name]=r.json()['id']
for n,cat,q in [('Phone','Electronics',20),('Laptop','Electronics',8),('Headphones','Electronics',25),('Lamp','Home',15),('Chair','Home',9),('Notebook','Books',40),('Novel','Books',30),('Tablet','Electronics',12)]:
 r=requests.post(base+'/products',data={'name':n,'price':'19.99','category_id':categories[cat],'initial_quantity':q},headers=h)
 if r.status_code not in (201,409):r.raise_for_status()
print('PASS: demo seed is present')

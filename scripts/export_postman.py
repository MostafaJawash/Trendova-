import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.main import app
spec=app.openapi(); folders={}
for path, methods in spec['paths'].items():
 for method, op in methods.items():
  for tag in op.get('tags',['other']): folders.setdefault(tag,[]).append({'name':op.get('summary',f'{method.upper()} {path}'),'request':{'method':method.upper(),'header':[],'url':'{{baseUrl}}'+path}})
collection={'info':{'name':'Trendova v1','schema':'https://schema.getpostman.com/json/collection/v2.1.0/collection.json'},'variable':[{'key':'baseUrl','value':'http://localhost:8000'},{'key':'token','value':''}],'auth':{'type':'bearer','bearer':[{'key':'token','value':'{{token}}','type':'string'}]},'item':[{'name':k,'item':v} for k,v in folders.items()]}
Path('docs').mkdir(exist_ok=True)
for f in collection['item']:
 for item in f['item']:
  if item['request']['url'].endswith('/auth/login'):item['event']=[{'listen':'test','script':{'exec':['var jsonData = pm.response.json();','pm.collectionVariables.set("token", jsonData.access_token);']}}]
open('docs/postman_collection.json','w',encoding='utf8').write(json.dumps(collection,indent=2,default=str))

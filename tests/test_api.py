from io import BytesIO
from PIL import Image
from app.core.database import SessionLocal
from app.modules.orders.models import Order
from app.modules.notifications.models import Notification
from app.modules.orders import repository as order_repository
from app.modules.notifications import service as notification_service
from app.integrations.inventory.gateway import gateway
from .conftest import make_user

BASE='/api/v1'
def assert_error(response,code=None):
    body=response.json();assert set(body)=={'error'},body
    assert isinstance(body['error'].get('code'),str) and isinstance(body['error'].get('message'),str) and isinstance(body['error'].get('details'),list),body
    if code:assert body['error']['code']==code,body

def order(client,product_id,headers,quantity=1):
    return client.post(BASE+'/orders',json={'items':[{'product_id':product_id,'quantity':quantity,'price':'0.01'}]},headers=headers)

def valid_png():
    out=BytesIO();Image.new('RGB',(2,2),'blue').save(out,format='PNG');return out.getvalue()

def test_register_role_duplicate_and_profile_security(client):
    registered=client.post(BASE+'/auth/register',json={'email':'alpha@example.com','name':'alpha','password':'password123','role':'admin'})
    assert registered.status_code==201
    user=registered.json()
    h={'Authorization':'Bearer '+client.post(BASE+'/auth/login',json={'email':'alpha@example.com','password':'password123'}).json()['access_token']}
    assert user['role']=='user'
    duplicate=client.post(BASE+'/auth/register',json={'email':'alpha@example.com','name':'Again','password':'password123'})
    assert duplicate.status_code==409;assert_error(duplicate)
    r=client.put(BASE+'/auth/me',headers=h,json={'role':'admin','is_active':False})
    assert r.status_code==422;assert_error(r)
    assert client.get(BASE+'/auth/me',headers=h).json()['role']=='user'
    other,_=make_user(client,'other-profile@example.com')
    assert client.put(f"{BASE}/users/{other['id']}",headers=h,json={'name':'Evil'}).status_code==405
    assert client.get(BASE+'/auth/me',headers=h).json()['id']==user['id']

def test_login_rate_limit_and_generic_error(client):
    make_user(client,'ratelimit@example.com')
    for _ in range(5):
        r=client.post(BASE+'/auth/login',json={'email':'ratelimit@example.com','password':'wrong'})
        assert r.status_code==401;assert r.json()['error']['message']=='Invalid email or password'
    sixth=client.post(BASE+'/auth/login',json={'email':'ratelimit@example.com','password':'wrong'})
    assert sixth.status_code==429 and 'Retry-After' in sixth.headers;assert_error(sixth,'TOO_MANY_ATTEMPTS')

def test_logout_and_password_change(client):
    user,h=make_user(client,'password@example.com')
    wrong=client.put(BASE+'/auth/me',json={'current_password':'wrong','new_password':'newpassword123'},headers=h)
    assert wrong.status_code==400;assert_error(wrong,'INVALID_CURRENT_PASSWORD')
    changed=client.put(BASE+'/auth/me',json={'current_password':'password123','new_password':'newpassword123'},headers=h)
    assert changed.status_code==200
    assert client.get(BASE+'/auth/me',headers=h).status_code==401
    h2={'Authorization':'Bearer '+client.post(BASE+'/auth/login',json={'email':'password@example.com','password':'newpassword123'}).json()['access_token']}
    assert client.post(BASE+'/auth/logout',headers=h2).status_code==204
    assert client.get(BASE+'/auth/me',headers=h2).status_code==401

def test_all_protected_routes_require_token(client):
    routes=[('get','/auth/me'),('put','/auth/me'),('post','/auth/logout'),('get','/users/me'),('put','/users/me'),('get','/users'),('get','/users/1'),('delete','/users/1'),('get','/categories'),('post','/categories'),('put','/categories/1'),('delete','/categories/1'),('get','/products'),('get','/products/1'),('post','/products'),('put','/products/1'),('put','/products/1/stock'),('delete','/products/1'),('get','/favorites'),('post','/favorites/1'),('delete','/favorites/1'),('get','/orders'),('get','/orders/1'),('post','/orders'),('patch','/orders/1/status'),('get','/notifications'),('patch','/notifications/1/read'),('post','/notifications/read-all'),('get','/dashboard/stats')]
    for method,path in routes:
        r=getattr(client,method)(BASE+path)
        assert r.status_code==401,(method,path,r.status_code,r.text)
        assert_error(r)

def test_order_ownership_status_and_total(setup):
    c=setup['client'];p=setup['product']['id'];a,ha=make_user(c,'owner@example.com');b,hb=make_user(c,'other@example.com')
    created=order(c,p,ha,2);assert created.status_code==201,created.text
    assert created.json()['total_amount']=='25.00'
    oid=created.json()['id']
    forbidden=c.get(f'{BASE}/orders/{oid}',headers=hb);assert forbidden.status_code==403;assert_error(forbidden,'FORBIDDEN')
    forbidden=c.patch(f'{BASE}/orders/{oid}/status',headers=ha,json={'status':'confirmed'});assert forbidden.status_code==403
    changed=c.patch(f'{BASE}/orders/{oid}/status',headers=setup['admin'],json={'status':'confirmed'});assert changed.status_code==200
    invalid=c.patch(f'{BASE}/orders/{oid}/status',headers=setup['admin'],json={'status':'delivered'});assert invalid.status_code==409;assert_error(invalid,'INVALID_STATUS_TRANSITION')

def test_insufficient_stock_no_order(setup):
    c=setup['client'];_,h=make_user(c,'stock@example.com')
    r=order(c,setup['product']['id'],h,11)
    assert r.status_code==409;assert_error(r,'INSUFFICIENT_STOCK')
    with SessionLocal() as db:assert db.query(Order).count()==0

def test_db_failure_releases_reservation(setup,monkeypatch):
    c=setup['client'];_,h=make_user(c,'dbfail@example.com');p=setup['product']['id']
    calls=[];original=gateway.release
    def release(id):calls.append(id);return original(id)
    def failed(*args,**kwargs):raise RuntimeError('database failed')
    monkeypatch.setattr(gateway,'release',release);monkeypatch.setattr(order_repository,'create',failed)
    r=order(c,p,h)
    assert r.status_code==500;assert_error(r,'ORDER_CREATE_FAILED')
    assert len(calls)==1 and gateway.get_quantity(p)==10

def test_cancel_releases_stock(setup):
    c=setup['client'];_,h=make_user(c,'cancel@example.com');p=setup['product']['id']
    created=order(c,p,h,2);assert created.status_code==201
    assert gateway.get_quantity(p)==8
    r=c.patch(f"{BASE}/orders/{created.json()['id']}/status",headers=setup['admin'],json={'status':'cancelled'})
    assert r.status_code==200 and gateway.get_quantity(p)==10

def test_products_filters_sort_and_pagination(setup):
    c=setup['client'];h=setup['admin'];cat=setup['category']['id']
    _,user_h=make_user(c,'catalog@example.com')
    product_id=setup['product']['id']
    assert 'created_at' in c.get(f'{BASE}/products/{product_id}',headers=h).json()
    assert 'created_at' not in c.get(f'{BASE}/products/{product_id}',headers=user_h).json()
    c.post(BASE+'/products',headers=h,data={'name':'Tablet','description':'Large SMART device','price':'22.00','category_id':cat,'initial_quantity':1})
    r=c.get(BASE+'/products',headers=h,params={'category':cat,'minPrice':'12','maxPrice':'13','search':'PHONE','page':1,'limit':1})
    assert r.status_code==200 and r.json()['total']==1 and r.json()['pages']==1
    assert r.json()['items'][0]['name']=='Phone'
    assert c.get(BASE+'/categories',headers=h).json()['items'][0]['description']=='Arabic مرحبا'
    r=c.get(BASE+'/products',headers=h,params={'sort_by':'arbitrary'})
    assert r.status_code==422;assert_error(r)
    assert c.get(BASE+'/products',headers=h,params={'minPrice':20,'maxPrice':10}).status_code==422

def test_images_and_soft_delete(setup):
    c=setup['client'];h=setup['admin'];cat=setup['category']['id'];_,uh=make_user(c,'history@example.com')
    data={'name':'Image product','price':'2','category_id':cat,'initial_quantity':2}
    good=c.post(BASE+'/products',headers=h,data=data,files={'image':('test.png',valid_png(),'image/png')})
    assert good.status_code==201,good.text
    assert good.json()['image_url'].startswith('/media/')
    bad=c.post(BASE+'/products',headers=h,data=data,files={'image':('fake.png',b'not-an-image','image/png')})
    assert bad.status_code==422;assert_error(bad,'INVALID_IMAGE')
    big=c.post(BASE+'/products',headers=h,data=data,files={'image':('huge.png',b'x'*(5*1024*1024+1),'image/png')})
    assert big.status_code==422;assert_error(big,'INVALID_IMAGE')
    p=setup['product']['id'];old=order(c,p,uh);assert old.status_code==201
    assert c.delete(f'{BASE}/products/{p}',headers=h).status_code==204
    listed=c.get(BASE+'/products',headers=uh).json()['items']
    assert p not in [x['id'] for x in listed]
    assert c.get(f"{BASE}/orders/{old.json()['id']}",headers=uh).json()['items'][0]['product_name']=='Phone'

def test_favorites_idempotent_and_dashboard(setup):
    c=setup['client'];_,h=make_user(c,'favorite@example.com');p=setup['product']['id']
    assert c.post(f'{BASE}/favorites/{p}',headers=h).status_code==201
    assert c.post(f'{BASE}/favorites/{p}',headers=h).status_code==200
    assert c.get(BASE+'/favorites',headers=h).json()['total']==1
    assert c.get(BASE+'/dashboard/stats',headers=h).status_code==403
    d=c.get(BASE+'/dashboard/stats',headers=setup['admin'])
    assert d.status_code==200 and len(d.json()['orders_last_7_days'])==7

def test_notifications_and_failure_isolation(setup,monkeypatch):
    c=setup['client'];a,ha=make_user(c,'notifya@example.com');b,hb=make_user(c,'notifyb@example.com');p=setup['product']['id']
    created=order(c,p,ha);assert created.status_code==201
    assert c.get(BASE+'/notifications',headers=ha).json()['total']==1
    assert c.get(BASE+'/notifications',headers=hb).json()['total']==0
    notification_id=c.get(BASE+'/notifications',headers=ha).json()['items'][0]['id']
    assert c.patch(f'{BASE}/notifications/{notification_id}/read',headers=hb).status_code==403
    with SessionLocal() as db:assert db.query(Notification).filter_by(user_id=a['id']).count()==1
    def broken(*args,**kwargs):raise RuntimeError('notification failure')
    monkeypatch.setattr(notification_service,'notify',broken)
    assert order(c,p,ha).status_code==201

def test_error_shapes_and_headers(setup):
    c=setup['client'];h=setup['admin']
    paths=[('/api/v1/products/999',404),('/api/v1/products?sort_by=bad',422),('/api/v1/auth/me',401),('/api/v1/no-such-route',404)]
    for path,status in paths:
        r=c.get(path,headers=h if status!=401 else {})
        assert r.status_code==status;assert_error(r)
        assert r.headers['X-Content-Type-Options']=='nosniff' and r.headers['X-Frame-Options']=='DENY'
        assert r.headers['Cache-Control']=='no-store'
        assert "script-src 'self'" in r.headers['Content-Security-Policy']
    for path in ('/docs','/redoc'):
        r=c.get(path);assert r.status_code==200
        assert "'unsafe-inline'" in r.headers['Content-Security-Policy']
    assert "'unsafe-inline'" not in c.get('/openapi.json').headers['Content-Security-Policy']
    spec=c.get('/openapi.json').json()
    for path,methods in spec['paths'].items():
        if not path.startswith('/api/v1/'):continue
        for operation in methods.values():
            assert operation['tags'] and operation['summary'] and operation['description']
            for code in ('401','403','404','409','422','429','503'):assert code in operation['responses'],(path,code)

def test_notifications_table_created_on_startup(client):
    from sqlalchemy import inspect
    from app.core.database import engine
    assert 'notifications' in inspect(engine).get_table_names()

def test_unexpected_error_shape_and_headers(setup,monkeypatch):
    from app.modules.products import service as product_service
    def broken(*args,**kwargs):raise RuntimeError('internal detail must stay private')
    monkeypatch.setattr(product_service,'product',broken)
    r=setup['client'].get(f"{BASE}/products/{setup['product']['id']}",headers=setup['admin'])
    assert r.status_code==500;assert_error(r,'INTERNAL_ERROR')
    assert 'internal detail' not in r.text
    assert r.headers['X-Frame-Options']=='DENY'

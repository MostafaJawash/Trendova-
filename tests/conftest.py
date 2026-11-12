import os
import tempfile
from pathlib import Path
import pytest
from sqlalchemy import delete

_test_dir=tempfile.mkdtemp(prefix='trendova_test_')
os.environ['DATABASE_URL']=os.getenv('TEST_DATABASE_URL',f'sqlite:///{_test_dir}/test.db')
os.environ['UPLOAD_DIR']=str(Path(_test_dir,'uploads'))
os.environ['SECRET_KEY']='test-only-secret-key-with-at-least-32-characters'
os.environ['ADMIN_EMAIL']='admin@test.example'
os.environ['ADMIN_PASSWORD']='adminpassword1'

from fastapi.testclient import TestClient
from app.main import app
from app.core.database import SessionLocal
from app.core.tokens import RevokedToken
from app.core.rate_limiter import limiter
from app.integrations.inventory.gateway import gateway
from app.modules.users.models import User
from app.modules.products.models import Product, Category, Favorite
from app.modules.orders.models import Order, OrderItem
from app.modules.notifications.models import Notification

@pytest.fixture
def client():
    with TestClient(app) as c:
        with SessionLocal() as db:
            for model in (Notification,RevokedToken,Favorite,OrderItem,Order,Product,Category): db.execute(delete(model))
            db.execute(delete(User).where(User.email!='admin@test.example'))
            db.commit()
        with gateway.lock: gateway.stock.clear();gateway.reservations.clear()
        with limiter.lock: limiter.entries.clear()
        yield c

@pytest.fixture
def setup(client):
    base='/api/v1'
    admin=client.post(base+'/auth/login',json={'email':'admin@test.example','password':'adminpassword1'})
    assert admin.status_code==200,admin.text
    admin_h={'Authorization':'Bearer '+admin.json()['access_token']}
    category=client.post(base+'/categories',json={'name':'Electronics','description':'Arabic مرحبا'},headers=admin_h)
    assert category.status_code==201,category.text
    product=client.post(base+'/products',data={'name':'Phone','description':'Smart device','price':'12.50','category_id':category.json()['id'],'initial_quantity':'10'},headers=admin_h)
    assert product.status_code==201,product.text
    return {'client':client,'base':base,'admin':admin_h,'category':category.json(),'product':product.json()}

def make_user(client, email):
    base='/api/v1'
    r=client.post(base+'/auth/register',json={'email':email,'name':email.split('@')[0],'password':'password123'})
    assert r.status_code==201,r.text
    login=client.post(base+'/auth/login',json={'email':email,'password':'password123'})
    assert login.status_code==200,login.text
    return r.json(),{'Authorization':'Bearer '+login.json()['access_token']}


def pytest_collection_modifyitems(config, items):
    """Tests that assert on the in-memory fake inventory cannot pass when the app talks to the real Go service
    (INVENTORY_MODE=grpc): skip them there instead of failing (they run in fake mode)."""
    if os.getenv('INVENTORY_MODE', 'fake') != 'grpc':
        return
    import inspect
    skip = pytest.mark.skip(reason='asserts on the in-memory fake inventory; not applicable with INVENTORY_MODE=grpc')
    for item in items:
        try:
            src = inspect.getsource(item.function)
        except (OSError, TypeError, AttributeError):
            continue
        import re
        if re.search(r'gateway\.(get_quantity|release|reserve|set_stock|stock|reservations)', src) or 'FakeInventory' in src:
            item.add_marker(skip)

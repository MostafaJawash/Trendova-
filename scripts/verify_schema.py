"""Compare the running database with the checked-in original SQL schema."""
import re
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import inspect
from app.core.database import engine

sql=Path(__file__).resolve().parents[1].joinpath('app/sql/01_create_schema.sql').read_text(encoding='utf-8')
original={}
for table,body in re.findall(r'CREATE TABLE IF NOT EXISTS `([^`]+)` \((.*?)\) ENGINE=',sql,re.S):
    original[table]=set(re.findall(r'^\s*`([^`]+)`\s+[A-Z]',body,re.M))
inspector=inspect(engine)
expected_additions={'users':{'is_active'},'products':{'is_active'},'orders':{'reservation_id'},'order_items':{'product_name'}}
for table,columns in original.items():
    actual={col['name'] for col in inspector.get_columns(table)}
    missing=columns-actual
    unexpected=actual-columns-expected_additions.get(table,set())
    print(f'{table}: original={len(columns)} actual={len(actual)} missing={sorted(missing)} unexpected={sorted(unexpected)}')
    assert not missing and not unexpected
for table in ('notifications','revoked_tokens'):
    assert table in inspector.get_table_names()
    print(f'{table}: exists')
indexes=inspector.get_indexes('notifications')
assert any(index['column_names']==['user_id','is_read','created_at'] for index in indexes)
print('notifications(user_id,is_read,created_at): indexed')
foreign_keys=inspector.get_foreign_keys('notifications')
assert any(key['referred_table']=='users' and key['constrained_columns']==['user_id'] for key in foreign_keys)
print('notifications.user_id: foreign key to users.id')

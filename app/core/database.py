from sqlalchemy import create_engine, event
from sqlalchemy import Integer
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import declarative_base, sessionmaker
from app.core.config import settings
kwargs = {'connect_args': {'check_same_thread': False}} if settings.sqlalchemy_url.startswith('sqlite') else {'pool_pre_ping': True}
engine = create_engine(settings.sqlalchemy_url, **kwargs)
if engine.dialect.name=='mysql':
    @event.listens_for(engine,'connect')
    def _utc_connection(connection, _):
        cursor=connection.cursor()
        try:cursor.execute("SET time_zone = '+00:00'")
        finally:cursor.close()
if settings.db_query_count:
    from app.core.query_counter import install as _install_query_counter
    _install_query_counter(engine)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
Base = declarative_base()
IdType = Integer().with_variant(mysql.BIGINT(unsigned=True), 'mysql')
def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

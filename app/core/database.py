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
# ---- Req 3: optional read replica (reads that may be slightly stale). None => everything on the primary ----
replica_engine = None
SessionReplica = None
if settings.use_read_replica and settings.replica_url and engine.dialect.name == 'mysql':
    replica_engine = create_engine(settings.replica_url, pool_pre_ping=True, connect_args={'connect_timeout': 2})
    @event.listens_for(replica_engine, 'connect')
    def _utc_replica_connection(connection, _):
        cursor = connection.cursor()
        try: cursor.execute("SET time_zone = '+00:00'")
        finally: cursor.close()
    if settings.db_query_count:
        _install_query_counter(replica_engine)
    SessionReplica = sessionmaker(bind=replica_engine, autoflush=False, autocommit=False, expire_on_commit=False)
Base = declarative_base()
IdType = Integer().with_variant(mysql.BIGINT(unsigned=True), 'mysql')
def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

import logging as _logging, time as _time
_log = _logging.getLogger(__name__)
_replica_down_until = 0.0
REPLICA_BREAKER_SECONDS = 5.0

def replica_session_or_none():
    """A replica session whose connection is verified (pool_pre_ping), or None if the replica is unusable.
    A failure opens a 5 s circuit breaker so a dead replica costs one short timeout, not one per request."""
    global _replica_down_until
    if SessionReplica is None or _time.monotonic() < _replica_down_until:
        return None
    db = SessionReplica()
    try:
        db.connection()
        return db
    except Exception as exc:
        _replica_down_until = _time.monotonic() + REPLICA_BREAKER_SECONDS
        _log.warning('Read replica unavailable (%s); using the primary for %.0fs', type(exc).__name__, REPLICA_BREAKER_SECONDS)
        try: db.close()
        except Exception: pass
        return None

def route_read(user_id=None, products=False, primary=None):
    """Pick the session for a read that may be slightly stale: replica unless disabled/down/marker present.
    Redis unreachable counts as "marker present" (cannot prove freshness) -> primary.

    Returns (session, owned). When the PRIMARY is chosen and the request already holds a primary session (`primary`,
    the one the auth dependency uses) that same session is reused: opening a second primary connection per request
    exhausted the 15-connection pool under concurrency (every request held one and waited for another until pool_timeout).
    The caller closes the session only when owned is True."""
    from app.core import redis as rds
    if SessionReplica is not None and not rds.has_marker(user_id, products):
        db = replica_session_or_none()
        if db is not None:
            return db, True
    if primary is not None:
        return primary, False
    return SessionLocal(), True

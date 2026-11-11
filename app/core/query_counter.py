"""Opt-in SQL statement counter used to prove N+1 behaviour.

* The app installs the listener only when DB_QUERY_COUNT=1 and then exposes the number of
  statements each request issued in the X-DB-Query-Count response header.
* Tests use the very same counter through `count_queries()`.
Counting is per request/task via a ContextVar, so concurrent requests do not mix.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from sqlalchemy import event

class QueryLog:
    """Statement counter; `statements` keeps the SQL text (capped) for debugging."""
    def __init__(self, keep=50):
        self.count = 0
        self.statements = []
        self._keep = keep

_current: ContextVar[QueryLog | None] = ContextVar('db_query_log', default=None)
_any_thread: QueryLog | None = None  # tests: count statements from every thread (TestClient runs the app in a portal thread)
_installed = set()

def install(engine):
    """Attach the counting listener to an engine (idempotent)."""
    if id(engine) in _installed:
        return
    _installed.add(id(engine))
    @event.listens_for(engine, 'before_cursor_execute')
    def _count(conn, cursor, statement, parameters, context, executemany):
        log = _current.get() or _any_thread
        if log is not None:
            log.count += 1
            if len(log.statements) < log._keep:
                log.statements.append(statement)

@contextmanager
def count_queries(any_thread=False):
    """Count statements issued inside the block. Per-request by default (ContextVar);
    any_thread=True counts every thread (single-threaded tests only)."""
    global _any_thread
    log = QueryLog()
    if any_thread:
        _any_thread = log
        try:
            yield log
        finally:
            _any_thread = None
        return
    token = _current.set(log)
    try:
        yield log
    finally:
        _current.reset(token)

import pytest
from app.core import query_counter
from app.core.database import engine


@pytest.fixture
def sql_counter():
    """Counts SQL statements with the same counter the app exposes as X-DB-Query-Count."""
    query_counter.install(engine)
    with query_counter.count_queries(any_thread=True) as log:
        yield log

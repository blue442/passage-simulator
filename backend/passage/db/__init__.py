from collections.abc import Iterator
from contextlib import contextmanager

import psycopg

from passage.config import Settings


@contextmanager
def get_connection(settings: Settings) -> Iterator[psycopg.Connection]:
    conn = psycopg.connect(settings.database_url)
    conn.prepare_threshold = None
    try:
        yield conn
    finally:
        conn.close()

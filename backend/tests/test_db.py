import os

from passage.config import Settings
from passage.db import get_connection

LOCAL_SUPABASE_DSN = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"


def test_app_meta_schema_row_is_readable() -> None:
    settings = Settings(
        auth_token="test-token",
        database_url=os.environ.get("PASSAGE_DATABASE_URL", LOCAL_SUPABASE_DSN),
        cron_secret="test-cron-secret",
    )

    with get_connection(settings) as conn:
        with conn.cursor() as cursor:
            cursor.execute("select value from app_meta where key = 'schema'")
            row = cursor.fetchone()

    assert row == ("phase-0.5",)

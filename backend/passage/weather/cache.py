# CONTRACT — see specs/weather-cache.md §2-§3.
#
# This module does I/O (psycopg) — explicitly NOT part of passage.engine, which must stay pure.
#
# Cursors use binary=True: psycopg's default TEXT result format for `double precision` columns
# (latitude/longitude here) is lossy by one ULP on the way out. See passage/db/passages.py's
# module docstring for the full story. (The jsonb `variables` column is unaffected -- verified
# JSON-encoded floats round-trip exactly regardless of cursor format.)
from datetime import datetime
from uuid import UUID

import psycopg
from psycopg.types.json import Json

from passage.engine.constants import TILE_RESOLUTION_DEG


def snap_tile(lat: float, lon: float) -> tuple[int, int, float, float]:
    """Snap (lat, lon) to the weather tile grid. Returns (lat_idx, lon_idx, snapped_latitude,
    snapped_longitude) per specs/weather-cache.md §2. Integer indices avoid float-equality
    hazards in the cache primary key."""
    lat_idx = round((lat + 90.0) / TILE_RESOLUTION_DEG)
    lon_idx = round((lon + 180.0) / TILE_RESOLUTION_DEG)
    snapped_lat = lat_idx * TILE_RESOLUTION_DEG - 90.0
    snapped_lon = lon_idx * TILE_RESOLUTION_DEG - 180.0
    return lat_idx, lon_idx, snapped_lat, snapped_lon


def truncate_hour(time: datetime) -> datetime:
    return time.replace(minute=0, second=0, microsecond=0)


def insert_rows(
    conn: psycopg.Connection,
    passage_id: UUID,
    source: str,
    lat_idx: int,
    lon_idx: int,
    latitude: float,
    longitude: float,
    rows: dict[datetime, dict[str, float]],
    fetched_at: datetime,
) -> None:
    """Insert fetched rows for one (passage, source, tile). `rows` maps hour_utc -> engine-ready
    variables (e.g. the dict `client.fetch()` returns for this tile). Never overwrites an
    existing (passage, source, tile, hour) row — ON CONFLICT DO NOTHING is what makes even a
    still-revising recent hour deterministic across replays (specs/weather-cache.md §3)."""
    with conn.cursor(binary=True) as cur:
        for hour_utc, variables in rows.items():
            cur.execute(
                """
                insert into weather_cache
                    (passage_id, source, lat_idx, lon_idx, hour_utc, latitude, longitude, variables, fetched_at)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (passage_id, source, lat_idx, lon_idx, hour_utc) do nothing
                """,
                (
                    passage_id, source, lat_idx, lon_idx, truncate_hour(hour_utc),
                    latitude, longitude, Json(variables), fetched_at,
                ),
            )
    conn.commit()


def read_rows(
    conn: psycopg.Connection,
    passage_id: UUID,
    lat_idx_range: tuple[int, int],
    lon_idx_range: tuple[int, int],
    hour_range: tuple[datetime, datetime],
) -> list[dict]:
    """Read all cached rows for a passage within the given tile/hour box (inclusive on all
    bounds). Returns dicts with keys: source, lat_idx, lon_idx, hour_utc, latitude, longitude,
    variables — the shape `sampler.build_sampler` expects."""
    lat_lo, lat_hi = lat_idx_range
    lon_lo, lon_hi = lon_idx_range
    hour_lo, hour_hi = hour_range
    with conn.cursor(binary=True) as cur:
        cur.execute(
            """
            select source, lat_idx, lon_idx, hour_utc, latitude, longitude, variables
            from weather_cache
            where passage_id = %s
              and lat_idx between %s and %s
              and lon_idx between %s and %s
              and hour_utc between %s and %s
            """,
            (passage_id, lat_lo, lat_hi, lon_lo, lon_hi, hour_lo, hour_hi),
        )
        columns = [desc.name for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def prune_passage_weather(conn: psycopg.Connection, passage_id: UUID) -> None:
    """Delete all cached weather for a passage (specs/weather-cache.md §5). Called on passage
    delete, not automatically on arrival — the Phase-7 debrief/replay needs the cache."""
    with conn.cursor(binary=True) as cur:
        cur.execute("delete from weather_cache where passage_id = %s", (passage_id,))
    conn.commit()

import os
import uuid
from datetime import UTC, datetime

import pytest
from psycopg.types.json import Json

from passage.config import Settings
from passage.db import get_connection
from passage.weather.cache import insert_rows, prune_passage_weather, read_rows, snap_tile

LOCAL_SUPABASE_DSN = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"


def _settings() -> Settings:
    return Settings(
        auth_token="test-token",
        database_url=os.environ.get("PASSAGE_DATABASE_URL", LOCAL_SUPABASE_DSN),
        cron_secret="test-cron-secret",
    )


@pytest.fixture
def passage_id():
    settings = _settings()
    new_id = uuid.uuid4()
    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into passage
                    (id, boat_key, origin_lat, origin_lon, destination_lat, destination_lon,
                     orders, seed, created_at, started_at, last_simulated_at, current_lat, current_lon)
                values (%s, 'cruiser35', 0.0, 0.0, 1.0, 1.0, %s, 1, now(), now(), now(), 0.0, 0.0)
                """,
                (new_id, Json({})),
            )
        conn.commit()
    yield new_id
    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute("delete from passage where id = %s", (new_id,))
        conn.commit()


class TestSnapTile:
    def test_snaps_to_grid(self) -> None:
        lat_idx, lon_idx, snapped_lat, snapped_lon = snap_tile(0.0, 0.0)
        assert (lat_idx, lon_idx) == (360, 720)
        assert snapped_lat == pytest.approx(0.0)
        assert snapped_lon == pytest.approx(0.0)

    def test_snaps_nearby_point_to_nearest_grid_line(self) -> None:
        # 0.1 is closer to the 0.0 grid line than to 0.25 (round-to-nearest, not floor).
        lat_idx, lon_idx, snapped_lat, snapped_lon = snap_tile(0.1, 0.1)
        assert (lat_idx, lon_idx) == (360, 720)
        assert snapped_lat == pytest.approx(0.0)

    def test_snaps_negative_coordinates(self) -> None:
        lat_idx, lon_idx, snapped_lat, snapped_lon = snap_tile(-0.25, -0.25)
        assert snapped_lat == pytest.approx(-0.25)
        assert snapped_lon == pytest.approx(-0.25)


class TestInsertAndReadRoundTrip:
    def test_round_trip(self, passage_id) -> None:
        settings = _settings()
        lat_idx, lon_idx, lat, lon = snap_tile(10.0, 20.0)
        hour = datetime(2026, 1, 1, 6, tzinfo=UTC)

        with get_connection(settings) as conn:
            insert_rows(
                conn, passage_id, "om-weather", lat_idx, lon_idx, lat, lon,
                rows={hour: {"wind_speed_kn": 12.5, "wind_dir_deg": 270.0, "gust_kn": 15.0, "pressure_hpa": 1013.0}},
                fetched_at=datetime.now(UTC),
            )

        with get_connection(settings) as conn:
            rows = read_rows(
                conn, passage_id,
                lat_idx_range=(lat_idx, lat_idx), lon_idx_range=(lon_idx, lon_idx),
                hour_range=(hour, hour),
            )

        assert len(rows) == 1
        assert rows[0]["source"] == "om-weather"
        assert rows[0]["lat_idx"] == lat_idx
        assert rows[0]["lon_idx"] == lon_idx
        assert rows[0]["variables"] == {
            "wind_speed_kn": 12.5, "wind_dir_deg": 270.0, "gust_kn": 15.0, "pressure_hpa": 1013.0,
        }

    def test_read_rows_respects_box_and_hour_bounds(self, passage_id) -> None:
        settings = _settings()
        lat_idx, lon_idx, lat, lon = snap_tile(10.0, 20.0)
        hour_in = datetime(2026, 1, 1, 6, tzinfo=UTC)
        hour_out = datetime(2026, 1, 1, 12, tzinfo=UTC)

        with get_connection(settings) as conn:
            insert_rows(
                conn, passage_id, "om-weather", lat_idx, lon_idx, lat, lon,
                rows={
                    hour_in: {"wind_speed_kn": 1.0, "wind_dir_deg": 1.0, "gust_kn": 1.0, "pressure_hpa": 1.0},
                    hour_out: {"wind_speed_kn": 2.0, "wind_dir_deg": 2.0, "gust_kn": 2.0, "pressure_hpa": 2.0},
                },
                fetched_at=datetime.now(UTC),
            )

        with get_connection(settings) as conn:
            rows = read_rows(
                conn, passage_id,
                lat_idx_range=(lat_idx, lat_idx), lon_idx_range=(lon_idx, lon_idx),
                hour_range=(hour_in, hour_in),
            )
        assert len(rows) == 1
        assert rows[0]["hour_utc"] == hour_in


class TestNeverOverwrite:
    def test_reinserting_a_changed_value_leaves_the_original(self, passage_id) -> None:
        settings = _settings()
        lat_idx, lon_idx, lat, lon = snap_tile(10.0, 20.0)
        hour = datetime(2026, 1, 1, 6, tzinfo=UTC)

        with get_connection(settings) as conn:
            insert_rows(
                conn, passage_id, "om-weather", lat_idx, lon_idx, lat, lon,
                rows={hour: {"wind_speed_kn": 12.5, "wind_dir_deg": 270.0, "gust_kn": 15.0, "pressure_hpa": 1013.0}},
                fetched_at=datetime.now(UTC),
            )
        # Re-fetch "revised" the same hour with a different value -- must NOT overwrite.
        with get_connection(settings) as conn:
            insert_rows(
                conn, passage_id, "om-weather", lat_idx, lon_idx, lat, lon,
                rows={hour: {"wind_speed_kn": 99.9, "wind_dir_deg": 999.0, "gust_kn": 999.0, "pressure_hpa": 999.0}},
                fetched_at=datetime.now(UTC),
            )

        with get_connection(settings) as conn:
            rows = read_rows(
                conn, passage_id,
                lat_idx_range=(lat_idx, lat_idx), lon_idx_range=(lon_idx, lon_idx),
                hour_range=(hour, hour),
            )
        assert len(rows) == 1
        assert rows[0]["variables"]["wind_speed_kn"] == 12.5


class TestPrunePassageWeather:
    def test_deletes_all_rows_for_the_passage(self, passage_id) -> None:
        settings = _settings()
        lat_idx, lon_idx, lat, lon = snap_tile(10.0, 20.0)
        hour = datetime(2026, 1, 1, 6, tzinfo=UTC)

        with get_connection(settings) as conn:
            insert_rows(
                conn, passage_id, "om-weather", lat_idx, lon_idx, lat, lon,
                rows={hour: {"wind_speed_kn": 1.0, "wind_dir_deg": 1.0, "gust_kn": 1.0, "pressure_hpa": 1.0}},
                fetched_at=datetime.now(UTC),
            )
            prune_passage_weather(conn, passage_id)

        with get_connection(settings) as conn:
            rows = read_rows(
                conn, passage_id,
                lat_idx_range=(lat_idx, lat_idx), lon_idx_range=(lon_idx, lon_idx),
                hour_range=(hour, hour),
            )
        assert rows == []

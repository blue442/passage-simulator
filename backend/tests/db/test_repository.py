import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from passage.config import Settings
from passage.db import get_connection
from passage.db.passages import create_passage, get_passage, list_passages, update_orders
from passage.db.track import persist_catchup
from passage.engine.boats import get_boat
from passage.engine.constants import STEP
from passage.engine.orders import Orders, RoutingMode
from passage.engine.simulate import simulate_segment
from passage.engine.state import GeoPoint, PassageParams, PassageStatus, WeatherSample

LOCAL_SUPABASE_DSN = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"


def _settings() -> Settings:
    return Settings(
        auth_token="test-token",
        database_url=os.environ.get("PASSAGE_DATABASE_URL", LOCAL_SUPABASE_DSN),
        cron_secret="test-cron-secret",
    )


class _AlwaysWater:
    def is_water(self, lat: float, lon: float) -> bool:
        return True


def _constant_weather(ws: WeatherSample):
    def provider(lat: float, lon: float, time: datetime) -> WeatherSample:
        return ws
    return provider


@pytest.fixture
def conn():
    settings = _settings()
    with get_connection(settings) as connection:
        yield connection


@pytest.fixture
def passage(conn):
    origin = GeoPoint(lat=0.0, lon=0.0)
    destination = GeoPoint(lat=10.0, lon=0.0)
    orders = Orders(routing_mode=RoutingMode.WAYPOINT, waypoints=[destination])
    started_at = datetime(2026, 1, 1, tzinfo=UTC)
    created = create_passage(
        conn, boat_key="cruiser35", origin=origin, destination=destination,
        orders=orders, seed=1, started_at=started_at, name="Test Passage",
    )
    yield created
    with conn.cursor() as cur:
        cur.execute("delete from passage where id = %s", (created.id,))
    conn.commit()


class TestPassageRoundTrip:
    def test_create_and_get_round_trip(self, conn, passage) -> None:
        fetched = get_passage(conn, passage.id)
        assert fetched == passage
        assert fetched.state.position == passage.origin
        assert fetched.state.time == passage.started_at
        assert fetched.state.status == PassageStatus.ACTIVE

    def test_get_unknown_id_returns_none(self, conn) -> None:
        assert get_passage(conn, uuid4()) is None

    def test_list_passages_includes_created(self, conn, passage) -> None:
        ids = {p.id for p in list_passages(conn)}
        assert passage.id in ids

    def test_update_orders_persists(self, conn, passage) -> None:
        new_orders = Orders(routing_mode=RoutingMode.HEADING, fixed_heading_deg=90.0)
        update_orders(conn, passage.id, new_orders)
        fetched = get_passage(conn, passage.id)
        assert fetched.orders == new_orders


class TestPersistCatchup:
    def test_two_batches_have_contiguous_seqs_and_state_matches_last_track_point(self, conn, passage) -> None:
        boat = get_boat("cruiser35")
        params = PassageParams(
            boat=boat, orders=passage.orders, destination=passage.destination,
            seed=passage.seed, started_at=passage.started_at,
        )
        ws = WeatherSample(wind_speed_kn=10, wind_dir_deg=90, gust_kn=12, pressure_hpa=1013, wave_height_m=0.0)
        weather = _constant_weather(ws)
        land = _AlwaysWater()

        batch1 = simulate_segment(params, passage.state, weather, land, until=passage.started_at + 3 * STEP)
        persist_catchup(conn, passage.id, batch1)

        batch2 = simulate_segment(params, batch1.end_state, weather, land, until=passage.started_at + 6 * STEP)
        persist_catchup(conn, passage.id, batch2)

        with conn.cursor() as cur:
            cur.execute("select seq from track_point where passage_id = %s order by seq", (passage.id,))
            track_seqs = [row[0] for row in cur.fetchall()]
        assert track_seqs == list(range(6))

        with conn.cursor() as cur:
            cur.execute("select seq from log_entry where passage_id = %s order by seq", (passage.id,))
            log_seqs = [row[0] for row in cur.fetchall()]
        assert log_seqs == list(range(len(log_seqs)))  # contiguous from 0, whatever the count

        with conn.cursor() as cur:
            cur.execute(
                "select latitude, longitude, heading_deg, speed_kn from track_point "
                "where passage_id = %s and seq = 5",
                (passage.id,),
            )
            last_row = cur.fetchone()

        fetched = get_passage(conn, passage.id)
        assert fetched.state == batch2.end_state
        assert fetched.state.position.lat == pytest.approx(last_row[0])
        assert fetched.state.position.lon == pytest.approx(last_row[1])
        assert fetched.state.heading_deg == pytest.approx(last_row[2])
        assert fetched.state.speed_kn == pytest.approx(last_row[3])

    def test_second_batch_continues_seq_numbering_not_restart(self, conn, passage) -> None:
        boat = get_boat("cruiser35")
        params = PassageParams(
            boat=boat, orders=passage.orders, destination=passage.destination,
            seed=passage.seed, started_at=passage.started_at,
        )
        ws = WeatherSample(wind_speed_kn=10, wind_dir_deg=90, gust_kn=12, pressure_hpa=1013, wave_height_m=0.0)
        weather = _constant_weather(ws)
        land = _AlwaysWater()

        batch1 = simulate_segment(params, passage.state, weather, land, until=passage.started_at + 2 * STEP)
        persist_catchup(conn, passage.id, batch1)
        batch2 = simulate_segment(params, batch1.end_state, weather, land, until=passage.started_at + 4 * STEP)
        persist_catchup(conn, passage.id, batch2)

        with conn.cursor() as cur:
            cur.execute("select count(*) from track_point where passage_id = %s", (passage.id,))
            count = cur.fetchone()[0]
        assert count == 4  # 2 + 2, not overwritten/reset

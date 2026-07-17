# CONTRACT — see specs/engine-state.md §3 (VesselState is the authoritative resume state,
# denormalized onto the passage row); migration 20260715120000_phase1_schema.sql.
#
# All cursors use binary=True: psycopg's default TEXT result format for `double precision`
# columns is lossy by one ULP on the way out (Postgres's text output doesn't always emit enough
# significant digits to round-trip exactly), which would silently break chunk-invariance across
# a catch-up that persists VesselState between requests. Binary format round-trips bit-exact.
from datetime import UTC, datetime
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Json
from pydantic import BaseModel

from passage.engine.orders import Orders
from passage.engine.state import GeoPoint, PassageStatus, VesselState

_DEFAULT_MODULE_TOGGLES = {"navigation": True, "sail_plan": False, "events": False, "safety": False}

_PASSAGE_COLUMNS = (
    "id, name, boat_key, origin_lat, origin_lon, destination_lat, destination_lon, orders, "
    "module_toggles, difficulty, seed, status, created_at, started_at, last_simulated_at, "
    "current_lat, current_lon, current_heading_deg, current_speed_kn, active_waypoint_index, "
    "distance_run_nm"
)


class Passage(BaseModel):
    # `state` is the authoritative VesselState reconstructed from the row's denormalized
    # current_*/last_simulated_at/status columns (specs/engine-state.md §3). The row's top-level
    # `status` column exists purely as an indexed copy of state.status for fast filtering
    # (passage_status_idx) -- it is never a separate concept and is always written in lockstep.
    id: UUID
    name: str | None = None
    boat_key: str
    origin: GeoPoint
    destination: GeoPoint
    orders: Orders
    module_toggles: dict[str, bool]
    difficulty: str
    seed: int
    created_at: datetime
    started_at: datetime
    state: VesselState


def _row_to_passage(row: dict) -> Passage:
    state = VesselState(
        time=row["last_simulated_at"],
        position=GeoPoint(lat=row["current_lat"], lon=row["current_lon"]),
        heading_deg=row["current_heading_deg"],
        speed_kn=row["current_speed_kn"],
        active_waypoint_index=row["active_waypoint_index"],
        distance_run_nm=row["distance_run_nm"],
        status=PassageStatus(row["status"]),
    )
    return Passage(
        id=row["id"],
        name=row["name"],
        boat_key=row["boat_key"],
        origin=GeoPoint(lat=row["origin_lat"], lon=row["origin_lon"]),
        destination=GeoPoint(lat=row["destination_lat"], lon=row["destination_lon"]),
        orders=Orders.model_validate(row["orders"]),
        module_toggles=row["module_toggles"],
        difficulty=row["difficulty"],
        seed=row["seed"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        state=state,
    )


def create_passage(
    conn: psycopg.Connection,
    *,
    boat_key: str,
    origin: GeoPoint,
    destination: GeoPoint,
    orders: Orders,
    seed: int,
    started_at: datetime,
    name: str | None = None,
    module_toggles: dict[str, bool] | None = None,
    difficulty: str = "standard",
    created_at: datetime | None = None,
) -> Passage:
    passage_id = uuid4()
    created_at = created_at if created_at is not None else datetime.now(UTC)
    module_toggles = module_toggles if module_toggles is not None else dict(_DEFAULT_MODULE_TOGGLES)
    initial_state = VesselState(time=started_at, position=origin, heading_deg=0.0, speed_kn=0.0)

    with conn.cursor(binary=True) as cur:
        cur.execute(
            """
            insert into passage
                (id, name, boat_key, origin_lat, origin_lon, destination_lat, destination_lon,
                 orders, module_toggles, difficulty, seed, status, created_at, started_at,
                 last_simulated_at, current_lat, current_lon, current_heading_deg,
                 current_speed_kn, active_waypoint_index, distance_run_nm)
            values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                passage_id, name, boat_key, origin.lat, origin.lon,
                destination.lat, destination.lon,
                Json(orders.model_dump(mode="json")), Json(module_toggles), difficulty, seed,
                initial_state.status.value, created_at, started_at, initial_state.time,
                initial_state.position.lat, initial_state.position.lon,
                initial_state.heading_deg, initial_state.speed_kn,
                initial_state.active_waypoint_index, initial_state.distance_run_nm,
            ),
        )
    conn.commit()
    return Passage(
        id=passage_id, name=name, boat_key=boat_key, origin=origin, destination=destination,
        orders=orders, module_toggles=module_toggles, difficulty=difficulty, seed=seed,
        created_at=created_at, started_at=started_at, state=initial_state,
    )


def get_passage(conn: psycopg.Connection, passage_id: UUID) -> Passage | None:
    with conn.cursor(binary=True) as cur:
        cur.execute(f"select {_PASSAGE_COLUMNS} from passage where id = %s", (passage_id,))
        row = cur.fetchone()
        if row is None:
            return None
        columns = [desc.name for desc in cur.description]
        return _row_to_passage(dict(zip(columns, row)))


def list_passages(conn: psycopg.Connection) -> list[Passage]:
    with conn.cursor(binary=True) as cur:
        cur.execute(f"select {_PASSAGE_COLUMNS} from passage order by created_at")
        columns = [desc.name for desc in cur.description]
        return [_row_to_passage(dict(zip(columns, row))) for row in cur.fetchall()]


def update_orders(conn: psycopg.Connection, passage_id: UUID, orders: Orders) -> None:
    with conn.cursor(binary=True) as cur:
        cur.execute(
            "update passage set orders = %s where id = %s",
            (Json(orders.model_dump(mode="json")), passage_id),
        )
    conn.commit()

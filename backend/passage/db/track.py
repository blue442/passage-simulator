# CONTRACT — see specs/engine-state.md §3/§7; migration 20260715120000_phase1_schema.sql.
#
# Uses binary=True cursors: see passage/db/passages.py's module docstring for why (lossy float
# text round-trip otherwise, which would break chunk-invariance for the persisted VesselState).
from uuid import UUID

import psycopg
from psycopg.types.json import Json

from passage.engine.state import SegmentResult


def persist_catchup(conn: psycopg.Connection, passage_id: UUID, result: SegmentResult) -> None:
    """Append a catch-up segment's track points + log entries with contiguous, monotonic `seq`
    per passage, and update the passage row's denormalized VesselState + last_simulated_at.
    Runs as one transaction (commit only at the end) so a partial catch-up is never persisted."""
    with conn.cursor(binary=True) as cur:
        cur.execute("select coalesce(max(seq), -1) from track_point where passage_id = %s", (passage_id,))
        next_track_seq = cur.fetchone()[0] + 1
        for i, tp in enumerate(result.track_points):
            cur.execute(
                """
                insert into track_point
                    (passage_id, seq, time, latitude, longitude, heading_deg, speed_kn,
                     tws_kn, twd_deg, gust_kn, pressure_hpa, wave_height_m)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    passage_id, next_track_seq + i, tp.time, tp.position.lat, tp.position.lon,
                    tp.heading_deg, tp.speed_kn, tp.tws_kn, tp.twd_deg, tp.gust_kn,
                    tp.pressure_hpa, tp.wave_height_m,
                ),
            )

        cur.execute("select coalesce(max(seq), -1) from log_entry where passage_id = %s", (passage_id,))
        next_log_seq = cur.fetchone()[0] + 1
        for i, entry in enumerate(result.log_entries):
            cur.execute(
                """
                insert into log_entry (passage_id, seq, time, category, message, data)
                values (%s,%s,%s,%s,%s,%s)
                """,
                (passage_id, next_log_seq + i, entry.time, entry.category.value, entry.message, Json(entry.data)),
            )

        state = result.end_state
        cur.execute(
            """
            update passage set
                last_simulated_at = %s, current_lat = %s, current_lon = %s,
                current_heading_deg = %s, current_speed_kn = %s,
                active_waypoint_index = %s, distance_run_nm = %s, status = %s
            where id = %s
            """,
            (
                state.time, state.position.lat, state.position.lon, state.heading_deg,
                state.speed_kn, state.active_waypoint_index, state.distance_run_nm,
                state.status.value, passage_id,
            ),
        )
    conn.commit()

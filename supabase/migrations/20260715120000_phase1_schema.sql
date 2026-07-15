-- Phase 1 schema: passages, track points, log entries, weather cache.
-- CONTRACT (Pre-1 spec gate, 2026-07-15). Frozen; schema changes require a spec session.
-- Plain vanilla Postgres so CI can apply it with psql (see specs/deployment.md).

-- A voyage. The dynamic VesselState is denormalized onto this row as the authoritative
-- resume state; track_point / log_entry are append-only history. See specs/engine-state.md.
create table passage (
    id                    uuid primary key,
    name                  text,
    boat_key              text not null,              -- key into the code-side boat preset registry
    origin_lat            double precision not null,
    origin_lon            double precision not null,
    destination_lat       double precision not null,
    destination_lon       double precision not null,
    orders                jsonb not null,             -- Orders v0 document (specs/orders.md)
    module_toggles        jsonb not null default '{"navigation": true, "sail_plan": false, "events": false, "safety": false}'::jsonb,
    difficulty            text not null default 'standard',   -- placeholder enum; tuned Phase 5
    seed                  bigint not null,            -- per-passage RNG seed (events are Phase 5)
    status                text not null default 'active',     -- active | arrived | grounded (Phase 5 adds more)
    created_at            timestamptz not null,
    started_at            timestamptz not null,       -- sim-clock origin; may be <= created_at for testing
    last_simulated_at     timestamptz not null,       -- sim-clock position; always started_at + k*STEP

    -- authoritative current VesselState (resume point for the next catch-up)
    current_lat           double precision not null,
    current_lon           double precision not null,
    current_heading_deg   double precision not null default 0,
    current_speed_kn      double precision not null default 0,
    active_waypoint_index integer not null default 0,
    distance_run_nm       double precision not null default 0
);

create index passage_status_idx on passage (status);

-- One row per simulation step (10 min). Feeds the map line + instruments panel.
create table track_point (
    passage_id     uuid not null references passage(id) on delete cascade,
    seq            integer not null,          -- 0-based, monotonic per passage
    time           timestamptz not null,
    latitude       double precision not null,
    longitude      double precision not null,
    heading_deg    double precision not null,
    speed_kn       double precision not null,
    tws_kn         double precision not null,
    twd_deg        double precision not null,
    gust_kn        double precision not null,
    pressure_hpa   double precision not null,
    wave_height_m  double precision not null,
    primary key (passage_id, seq)
);

-- Narrative / event log. Phase 1: hourly conditions + departure/waypoint/arrival/grounding.
create table log_entry (
    passage_id  uuid not null references passage(id) on delete cascade,
    seq         integer not null,             -- 0-based, monotonic per passage
    time        timestamptz not null,
    category    text not null,                -- departure|conditions|waypoint|arrival|grounding (Phase 5 adds more)
    message     text not null,
    data        jsonb not null default '{}'::jsonb,
    primary key (passage_id, seq)
);

-- Cached Open-Meteo weather, per passage, never overwritten. See specs/weather-cache.md.
create table weather_cache (
    passage_id  uuid not null references passage(id) on delete cascade,
    source      text not null,                -- 'om-weather' | 'om-marine'
    lat_idx     integer not null,             -- snapped tile index: round((lat+90)/TILE_RESOLUTION_DEG)
    lon_idx     integer not null,             -- snapped tile index: round((lon+180)/TILE_RESOLUTION_DEG)
    hour_utc    timestamptz not null,         -- truncated to the hour
    latitude    double precision not null,    -- snapped tile latitude (for the API request)
    longitude   double precision not null,    -- snapped tile longitude
    variables   jsonb not null,               -- engine-ready values (knots/hPa/m) for this source
    fetched_at  timestamptz not null,
    primary key (passage_id, source, lat_idx, lon_idx, hour_utc)
);

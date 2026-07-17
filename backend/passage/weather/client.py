# CONTRACT — see specs/weather-cache.md §1.
#
# This module does I/O (httpx) — it is explicitly NOT part of passage.engine, which must stay
# pure. See tests/engine/test_purity.py for the tripwire that enforces the boundary.
#
# Live-spike findings (T1.1, 2026-07-17 — see this ticket's note in tickets/phase-1.md for the
# full record): both api.open-meteo.com/v1/forecast (wind/pressure) and
# marine-api.open-meteo.com/v1/marine (wave height) return complete, null-free hourly data for
# past hours all the way up to the current hour, at both open-ocean and coastal test points, with
# `past_days`/`start_date`+`end_date` working past 92 days on both endpoints. No ERA5 archive
# fallback is needed for Phase 1. `windspeed_unit=kn` is supported server-side and verified
# against the m/s values for the same hour (agrees to within the API's own rounding), so wind
# speeds arrive pre-converted — no client-side unit math is needed for wind, and pressure/
# wave_height are already in hPa/m.
from datetime import UTC, datetime

import httpx

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"

_SOURCE_CONFIG = {
    "om-weather": {
        "url": FORECAST_URL,
        "open_meteo_vars": ["wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "pressure_msl"],
        "engine_fields": {
            "wind_speed_10m": "wind_speed_kn",
            "wind_direction_10m": "wind_dir_deg",
            "wind_gusts_10m": "gust_kn",
            "pressure_msl": "pressure_hpa",
        },
        "extra_params": {"windspeed_unit": "kn"},
    },
    "om-marine": {
        "url": MARINE_URL,
        "open_meteo_vars": ["wave_height"],
        "engine_fields": {"wave_height": "wave_height_m"},
        "extra_params": {},
    },
}


def fetch(
    source: str,
    latitude: float,
    longitude: float,
    start_hour: datetime,
    end_hour: datetime,
    client: httpx.Client | None = None,
) -> dict[datetime, dict[str, float]]:
    """Fetch hourly data for one tile, covering every hour in [start_hour, end_hour] (both
    UTC, hour-truncated per specs/weather-cache.md §2). Returns {hour_utc: {engine_field: value}}
    with engine-ready field names/units. Raises httpx.HTTPStatusError on a non-2xx response, and
    ValueError for an unknown source. `client` may be injected for testing (e.g. an
    httpx.Client(transport=httpx.MockTransport(...)))."""
    if source not in _SOURCE_CONFIG:
        raise ValueError(f"unknown source {source!r}; expected one of {sorted(_SOURCE_CONFIG)}")
    config = _SOURCE_CONFIG[source]

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": ",".join(config["open_meteo_vars"]),
        "start_date": start_hour.date().isoformat(),
        "end_date": end_hour.date().isoformat(),
        "timezone": "UTC",
        **config["extra_params"],
    }

    owns_client = client is None
    http_client = client if client is not None else httpx.Client()
    try:
        response = http_client.get(config["url"], params=params, timeout=15.0)
        response.raise_for_status()
    finally:
        if owns_client:
            http_client.close()

    hourly = response.json()["hourly"]
    times = [datetime.fromisoformat(t).replace(tzinfo=UTC) for t in hourly["time"]]

    result: dict[datetime, dict[str, float]] = {}
    for i, hour_utc in enumerate(times):
        if hour_utc < start_hour or hour_utc > end_hour:
            continue
        result[hour_utc] = {
            config["engine_fields"][var]: hourly[var][i] for var in config["open_meteo_vars"]
        }
    return result

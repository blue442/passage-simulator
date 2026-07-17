from datetime import UTC, datetime, timedelta

import httpx
import pytest

from passage.weather.client import fetch

# Sample payload shapes captured from the live Open-Meteo APIs during the T1.1 spike
# (2026-07-17); see the client.py module docstring and tickets/phase-1.md for the full record.
OM_WEATHER_SAMPLE = {
    "latitude": 31.95,
    "longitude": -63.97,
    "hourly_units": {
        "time": "iso8601",
        "wind_speed_10m": "kn",
        "wind_direction_10m": "°",
        "wind_gusts_10m": "kn",
        "pressure_msl": "hPa",
    },
    "hourly": {
        "time": ["2026-07-17T12:00", "2026-07-17T13:00", "2026-07-17T14:00"],
        "wind_speed_10m": [7.9, 8.8, 9.6],
        "wind_direction_10m": [82, 85, 90],
        "wind_gusts_10m": [13.2, 14.0, 15.1],
        "pressure_msl": [1018.2, 1018.0, 1017.8],
    },
}

OM_MARINE_SAMPLE = {
    "latitude": 32.04,
    "longitude": -64.04,
    "hourly_units": {"time": "iso8601", "wave_height": "m"},
    "hourly": {
        "time": ["2026-07-17T12:00", "2026-07-17T13:00", "2026-07-17T14:00"],
        "wave_height": [1.02, 1.00, 1.00],
    },
}


def _mock_client(json_body: dict, capture: dict | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture["url"] = request.url
        return httpx.Response(200, json=json_body)

    return httpx.Client(transport=httpx.MockTransport(handler))


class TestFetchOmWeather:
    def test_parses_and_maps_engine_fields(self) -> None:
        client = _mock_client(OM_WEATHER_SAMPLE)
        result = fetch(
            "om-weather", 32.0, -64.0,
            datetime(2026, 7, 17, 12, tzinfo=UTC), datetime(2026, 7, 17, 14, tzinfo=UTC),
            client=client,
        )
        assert len(result) == 3
        assert result[datetime(2026, 7, 17, 12, tzinfo=UTC)] == {
            "wind_speed_kn": 7.9, "wind_dir_deg": 82, "gust_kn": 13.2, "pressure_hpa": 1018.2,
        }
        assert result[datetime(2026, 7, 17, 14, tzinfo=UTC)] == {
            "wind_speed_kn": 9.6, "wind_dir_deg": 90, "gust_kn": 15.1, "pressure_hpa": 1017.8,
        }

    def test_requests_windspeed_unit_kn(self) -> None:
        capture: dict = {}
        client = _mock_client(OM_WEATHER_SAMPLE, capture=capture)
        fetch(
            "om-weather", 32.0, -64.0,
            datetime(2026, 7, 17, 12, tzinfo=UTC), datetime(2026, 7, 17, 14, tzinfo=UTC),
            client=client,
        )
        assert capture["url"].host == "api.open-meteo.com"
        assert dict(capture["url"].params)["windspeed_unit"] == "kn"

    def test_filters_to_requested_hour_range(self) -> None:
        # start_date/end_date are date-granularity; fetch() must trim to the exact hour bounds.
        client = _mock_client(OM_WEATHER_SAMPLE)
        result = fetch(
            "om-weather", 32.0, -64.0,
            datetime(2026, 7, 17, 13, tzinfo=UTC), datetime(2026, 7, 17, 13, tzinfo=UTC),
            client=client,
        )
        assert list(result.keys()) == [datetime(2026, 7, 17, 13, tzinfo=UTC)]


class TestFetchOmMarine:
    def test_parses_and_maps_engine_fields(self) -> None:
        client = _mock_client(OM_MARINE_SAMPLE)
        result = fetch(
            "om-marine", 32.0, -64.0,
            datetime(2026, 7, 17, 12, tzinfo=UTC), datetime(2026, 7, 17, 14, tzinfo=UTC),
            client=client,
        )
        assert len(result) == 3
        assert result[datetime(2026, 7, 17, 12, tzinfo=UTC)] == {"wave_height_m": 1.02}

    def test_does_not_request_windspeed_unit(self) -> None:
        capture: dict = {}
        client = _mock_client(OM_MARINE_SAMPLE, capture=capture)
        fetch(
            "om-marine", 32.0, -64.0,
            datetime(2026, 7, 17, 12, tzinfo=UTC), datetime(2026, 7, 17, 14, tzinfo=UTC),
            client=client,
        )
        assert capture["url"].host == "marine-api.open-meteo.com"
        assert "windspeed_unit" not in dict(capture["url"].params)


class TestFetchErrors:
    def test_unknown_source_raises(self) -> None:
        with pytest.raises(ValueError):
            fetch(
                "om-bogus", 32.0, -64.0,
                datetime(2026, 7, 17, 12, tzinfo=UTC), datetime(2026, 7, 17, 14, tzinfo=UTC),
            )

    def test_non_2xx_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "server error"})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with pytest.raises(httpx.HTTPStatusError):
            fetch(
                "om-weather", 32.0, -64.0,
                datetime(2026, 7, 17, 12, tzinfo=UTC), datetime(2026, 7, 17, 14, tzinfo=UTC),
                client=client,
            )


@pytest.mark.live
class TestLiveSpike:
    # PLAN.md's Phase-1 spike: verify marine + wind/pressure past-hours availability against the
    # real API before building on it (specs/weather-cache.md §1). NOT run in CI (see pyproject.toml
    # addopts). Run explicitly with: uv run pytest tests/weather/test_client.py -m live
    def test_om_weather_recent_past_is_non_empty(self) -> None:
        now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        result = fetch("om-weather", 32.0, -64.0, now - timedelta(hours=6), now)
        assert len(result) >= 6
        for values in result.values():
            assert values["wind_speed_kn"] >= 0
            assert 0 <= values["wind_dir_deg"] < 360
            assert values["pressure_hpa"] > 900

    def test_om_marine_recent_past_is_non_empty(self) -> None:
        now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        result = fetch("om-marine", 32.0, -64.0, now - timedelta(hours=6), now)
        assert len(result) >= 6
        for values in result.values():
            assert values["wave_height_m"] >= 0

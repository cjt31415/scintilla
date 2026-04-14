"""Tests for scintilla.common.map_time — pure math, parsing, and conversion functions."""

import math
import pytest
import pytz
from datetime import datetime

from scintilla.common.utils import get_utm_zone, convert_to_utc
from scintilla.common.map_time import (
    haversine,
    bearing,
    bearing_to_cardinal,
    km_to_deg,
    km_to_miles,
    miles_to_km,
    parse_date_string,
    parse_location,
    convert_timezone,
    make_timezone_aware,
    process_dt_window,
)


# ---------------------------------------------------------------------------
# get_utm_zone
# ---------------------------------------------------------------------------
class TestGetUtmZone:
    def test_tucson(self):
        assert get_utm_zone(32.2, -110.9) == "12Q"

    def test_london(self):
        result = get_utm_zone(51.5, -0.1)
        assert result.startswith("30")

    def test_south_pole_band(self):
        result = get_utm_zone(-85.0, 0.0)
        assert result.endswith("C")

    def test_north_extreme_band(self):
        result = get_utm_zone(85.0, 0.0)
        assert result.endswith("X")

    def test_equator_band(self):
        result = get_utm_zone(0.0, 0.0)
        band = result[-1]
        assert band == "M"  # 0° lat falls in band M (0-8°N is N, but 0° itself → M)


# ---------------------------------------------------------------------------
# haversine
# ---------------------------------------------------------------------------
class TestHaversine:
    def test_same_point(self):
        assert haversine(32.0, -110.0, 32.0, -110.0) == 0.0

    def test_known_distance_km(self):
        # NYC to LA — approximately 3,944 km
        dist = haversine(40.7128, -74.0060, 34.0522, -118.2437)
        assert 3900 < dist < 4000

    def test_known_distance_miles(self):
        dist = haversine(40.7128, -74.0060, 34.0522, -118.2437, return_miles=True)
        assert 2400 < dist < 2500

    def test_short_distance(self):
        # Two points ~1 degree apart at equator ≈ 111 km
        dist = haversine(0.0, 0.0, 0.0, 1.0)
        assert 110 < dist < 112

    def test_antipodes(self):
        # Opposite sides of earth ≈ 20,000 km
        dist = haversine(0.0, 0.0, 0.0, 180.0)
        assert 20000 < dist < 20100


# ---------------------------------------------------------------------------
# bearing / bearing_to_cardinal
# ---------------------------------------------------------------------------
class TestBearing:
    def test_due_north(self):
        b = bearing(32.0, -110.0, 33.0, -110.0)
        assert b == 0.0  # Due north is exactly 0 degrees

    def test_due_east(self):
        b = bearing(0.0, 0.0, 0.0, 1.0)
        assert 89 < b < 91

    def test_cardinal_north(self):
        assert bearing_to_cardinal(0.0) == "N"
        assert bearing_to_cardinal(360.0) == "N"

    def test_cardinal_south(self):
        assert bearing_to_cardinal(180.0) == "S"

    def test_cardinal_east(self):
        assert bearing_to_cardinal(90.0) == "E"

    def test_cardinal_text(self):
        b = bearing(0.0, 0.0, 0.0, 1.0, return_txt=True)
        assert b == "E"


# ---------------------------------------------------------------------------
# km_to_deg
# ---------------------------------------------------------------------------
class TestKmToDeg:
    def test_latitude_conversion(self):
        # 1 degree latitude ≈ 111 km, so 111 km → ~1 degree
        deg = km_to_deg(111.111, 0.0, is_longitude=False)
        assert abs(deg - 1.0) < 0.01

    def test_longitude_at_equator(self):
        # At equator, 1 degree longitude ≈ 111 km
        deg = km_to_deg(111.111, 0.0, is_longitude=True)
        assert abs(deg - 1.0) < 0.01

    def test_longitude_at_high_latitude(self):
        # At 60°N, longitude degrees are ~half the equatorial distance
        deg_equator = km_to_deg(100, 0.0, is_longitude=True)
        deg_60 = km_to_deg(100, 60.0, is_longitude=True)
        assert deg_60 > deg_equator * 1.8  # roughly double


# ---------------------------------------------------------------------------
# km_to_miles / miles_to_km
# ---------------------------------------------------------------------------
class TestUnitConversions:
    def test_km_to_miles(self):
        assert abs(km_to_miles(1.0) - 0.621371) < 0.0001

    def test_miles_to_km(self):
        assert abs(miles_to_km(1.0) - 1.60934) < 0.001

    def test_roundtrip(self):
        assert abs(miles_to_km(km_to_miles(42.195)) - 42.195) < 0.001


# ---------------------------------------------------------------------------
# parse_date_string
# ---------------------------------------------------------------------------
class TestParseDateString:
    def test_date_only(self):
        dt, has_time = parse_date_string("2024-03-15")
        assert dt.year == 2024
        assert dt.month == 3
        assert dt.day == 15
        assert has_time is False

    def test_date_and_time(self):
        dt, has_time = parse_date_string("2024-03-15 14:30:00")
        assert has_time is True
        assert dt.hour == 14
        assert dt.minute == 30

    def test_date_time_no_seconds(self):
        dt, has_time = parse_date_string("2024-03-15 14:30")
        assert has_time is True


# ---------------------------------------------------------------------------
# parse_location
# ---------------------------------------------------------------------------
class TestParseLocation:
    def test_north_west(self):
        lat, lon = parse_location("34.0N, 118.2W")
        assert lat == 34.0
        assert lon == -118.2

    def test_south_east(self):
        lat, lon = parse_location("33.9S, 18.4E")
        assert lat == -33.9
        assert lon == 18.4


# ---------------------------------------------------------------------------
# convert_timezone
# ---------------------------------------------------------------------------
class TestConvertTimezone:
    def test_utc_to_pacific_string_input(self):
        result = convert_timezone("2024.07.04 19:00:00", "US/Pacific")
        assert result.hour == 12  # PDT = UTC-7

    def test_utc_to_pacific_datetime_input(self):
        dt = datetime(2024, 7, 4, 19, 0, 0)
        result = convert_timezone(dt, "US/Pacific")
        assert result.hour == 12

    def test_naive_output(self):
        result = convert_timezone("2024.01.01 12:00:00", "US/Eastern", use_naive=True)
        assert result.tzinfo is None

    def test_aware_output(self):
        result = convert_timezone("2024.01.01 12:00:00", "US/Eastern", use_naive=False)
        assert result.tzinfo is not None


# ---------------------------------------------------------------------------
# convert_to_utc / make_timezone_aware
# ---------------------------------------------------------------------------
class TestTimezoneConversions:
    def test_convert_naive_to_utc(self):
        naive_dt = datetime(2024, 7, 4, 12, 0, 0)
        utc_dt = convert_to_utc(naive_dt, "US/Pacific")
        assert utc_dt.hour == 19  # PDT = UTC-7

    def test_make_timezone_aware(self):
        naive = datetime(2024, 1, 1, 12, 0, 0)
        aware = make_timezone_aware(naive, "US/Pacific")
        assert aware.tzinfo is not None
        assert str(aware.tzinfo) == "US/Pacific"


# ---------------------------------------------------------------------------
# process_dt_window
# ---------------------------------------------------------------------------
class TestProcessDtWindow:
    def test_with_date_strings(self):
        num_days, start, end = process_dt_window(None, "2024-01-01", "2024-01-10")
        assert num_days == 9
        assert start.year == 2024
        assert end.hour == 23  # rounded up to end of day

    def test_with_datetime_strings_including_time(self):
        num_days, start, end = process_dt_window(None, "2024-01-01 08:00:00", "2024-01-10 20:00:00")
        assert num_days == 9
        assert end.hour == 20  # not rounded because time was specified

    def test_with_ndays(self):
        num_days, start, end = process_dt_window(7, None, None)
        assert num_days == 7
        assert start < end

    def test_no_inputs(self):
        num_days, start, end = process_dt_window(None, None, None)
        assert num_days == 0
        assert start is None
        assert end is None

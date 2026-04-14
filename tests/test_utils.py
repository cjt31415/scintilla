"""Tests for scintilla.common.utils — pure functions and simple geometry operations."""

from datetime import datetime

import geopandas as gpd
import pytest
import pytz
from shapely.geometry import LineString, MultiLineString, Point, Polygon

from scintilla.common.utils import (
    aoi_area_in_km2,
    clean_state_name,
    convert_to_utc,
    extract_coordinates,
    format_utc_to_string,
    geometry_gdf_to_json,
    get_utm_epsg_code,
    get_utm_zone,
    iterate_over_months,
    mission_data,
    parse_julian_date_from_path,
    polygon_to_bbox,
    reverse_polygon_order,
    state_abbr,
)

# ---------------------------------------------------------------------------
# polygon_to_bbox
# ---------------------------------------------------------------------------


class TestPolygonToBbox:
    def test_simple_rectangle(self):
        geom = {"coordinates": [[[-122.0, 38.0], [-121.0, 38.0], [-121.0, 39.0], [-122.0, 39.0], [-122.0, 38.0]]]}
        result = polygon_to_bbox(geom)
        assert result == [-122.0, 38.0, -121.0, 39.0]

    def test_single_point_polygon(self):
        geom = {"coordinates": [[[-110.0, 32.0], [-110.0, 32.0]]]}
        result = polygon_to_bbox(geom)
        assert result == [-110.0, 32.0, -110.0, 32.0]

    def test_southern_hemisphere(self):
        geom = {"coordinates": [[[20.0, -34.0], [21.0, -34.0], [21.0, -33.0], [20.0, -33.0], [20.0, -34.0]]]}
        west, south, east, north = polygon_to_bbox(geom)
        assert south < north
        assert west < east


# ---------------------------------------------------------------------------
# get_utm_epsg_code (utils version — takes lon, lat scalars)
# ---------------------------------------------------------------------------


class TestGetUtmEpsgCode:
    def test_northern_hemisphere(self):
        # Tucson, AZ — UTM zone 12N → EPSG 32612
        result = get_utm_epsg_code(-110.9, 32.2)
        assert result == "32612"

    def test_southern_hemisphere(self):
        # Cape Town — UTM zone 34S → EPSG 32734
        result = get_utm_epsg_code(18.4, -33.9)
        assert result == "32734"

    def test_prime_meridian(self):
        # London — UTM zone 30N
        result = get_utm_epsg_code(-0.1, 51.5)
        assert result == "32630"

    def test_dateline(self):
        # Just west of dateline
        result = get_utm_epsg_code(179.0, 0.0)
        assert result.startswith("326")


# ---------------------------------------------------------------------------
# get_utm_zone (utils version)
# ---------------------------------------------------------------------------


class TestGetUtmZone:
    def test_tucson(self):
        result = get_utm_zone(32.2, -110.9)
        assert result == "12Q"

    def test_equator(self):
        result = get_utm_zone(0.0, 0.0)
        zone_num = int(result[:-1])
        assert zone_num == 31

    def test_south_pole(self):
        result = get_utm_zone(-85.0, 0.0)
        assert result.endswith("C")

    def test_north_extreme(self):
        result = get_utm_zone(85.0, 0.0)
        assert result.endswith("X")


# ---------------------------------------------------------------------------
# mission_data
# ---------------------------------------------------------------------------


class TestMissionData:
    def test_glm(self):
        result = mission_data("GLM")
        assert result["short_name"] == "glmgoesL3"
        assert "provider_id" in result
        assert "version" in result

    def test_gedi(self):
        result = mission_data("GEDI")
        assert result["short_name"] == "GEDI02_B"

    def test_isslis(self):
        result = mission_data("ISSLIS")
        assert result["short_name"] == "isslis_v3_fin"

    def test_invalid_mission_raises(self):
        with pytest.raises(ValueError):
            mission_data("FAKE_MISSION")


# ---------------------------------------------------------------------------
# convert_to_utc
# ---------------------------------------------------------------------------


class TestConvertToUtc:
    def test_pacific_to_utc(self):
        local_dt = datetime(2024, 7, 4, 12, 0, 0)  # noon
        utc_dt = convert_to_utc(local_dt, "US/Pacific")
        assert utc_dt.hour == 19  # PDT = UTC-7

    def test_utc_to_utc(self):
        local_dt = datetime(2024, 1, 1, 0, 0, 0)
        utc_dt = convert_to_utc(local_dt, "UTC")
        assert utc_dt.hour == 0


# ---------------------------------------------------------------------------
# format_utc_to_string
# ---------------------------------------------------------------------------


class TestFormatUtcToString:
    def test_basic_format(self):
        dt = datetime(2024, 3, 15, 14, 30, 45, tzinfo=pytz.UTC)
        result = format_utc_to_string(dt)
        assert result == "2024-03-15 14:30:45Z"

    def test_midnight(self):
        dt = datetime(2024, 1, 1, 0, 0, 0, tzinfo=pytz.UTC)
        result = format_utc_to_string(dt)
        assert result == "2024-01-01 00:00:00Z"


# ---------------------------------------------------------------------------
# parse_julian_date_from_path
# ---------------------------------------------------------------------------


class TestParseJulianDateFromPath:
    def test_glm_filename(self):
        filename = "OR_GLM-L3-GLMF-M6_G18_s202323215130000_e202323215140000_c20232321514540.nc"
        result = parse_julian_date_from_path(filename)
        assert result.year == 2023
        assert result.tzinfo == pytz.UTC

    def test_another_glm_filename(self):
        filename = "OR_GLM-L2-LCFA_G18_s20240010000209_e20240010009529_c20240010010010.nc"
        result = parse_julian_date_from_path(filename)
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 1


# ---------------------------------------------------------------------------
# clean_state_name
# ---------------------------------------------------------------------------


class TestCleanStateName:
    def test_two_word_state(self):
        assert clean_state_name("New Mexico") == "new_mexico"

    def test_single_word(self):
        assert clean_state_name("Texas") == "texas"

    def test_already_clean(self):
        assert clean_state_name("california") == "california"


# ---------------------------------------------------------------------------
# state_abbr
# ---------------------------------------------------------------------------


class TestStateAbbr:
    def test_known_states(self):
        assert state_abbr("California") == "CA"
        assert state_abbr("New York") == "NY"
        assert state_abbr("Texas") == "TX"

    def test_unknown_state_raises(self):
        with pytest.raises(ValueError):
            state_abbr("Atlantis")


# ---------------------------------------------------------------------------
# reverse_polygon_order
# ---------------------------------------------------------------------------


class TestReversePolygonOrder:
    def test_closed_polygon(self):
        polygon = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
        result = reverse_polygon_order(polygon)
        # Should be reversed and closed
        assert result[0] == result[-1]
        assert result[0] == [0, 1]

    def test_open_polygon(self):
        polygon = [[0, 0], [1, 0], [1, 1]]
        result = reverse_polygon_order(polygon)
        assert result[0] == [1, 1]
        assert result[-1] == [1, 1]  # closed


# ---------------------------------------------------------------------------
# iterate_over_months
# ---------------------------------------------------------------------------


class TestIterateOverMonths:
    def test_three_months(self):
        start = datetime(2024, 1, 1)
        end = datetime(2024, 3, 1)
        months = list(iterate_over_months(start, end))
        assert len(months) == 3

    def test_same_month(self):
        dt = datetime(2024, 6, 15)
        months = list(iterate_over_months(dt, dt))
        assert len(months) == 1

    def test_year_boundary(self):
        start = datetime(2023, 11, 1)
        end = datetime(2024, 2, 1)
        months = list(iterate_over_months(start, end))
        assert len(months) == 4


# ---------------------------------------------------------------------------
# extract_coordinates (Tier 2 — needs shapely fixtures)
# ---------------------------------------------------------------------------


class TestExtractCoordinates:
    def test_point(self):
        gdf = gpd.GeoDataFrame(geometry=[Point(-110.0, 32.0)], crs="EPSG:4326")
        coords = extract_coordinates(gdf)
        assert len(coords) == 1
        assert coords[0] == (32.0, -110.0)  # lat, lon

    def test_polygon(self):
        poly = Polygon([(-110, 32), (-109, 32), (-109, 33), (-110, 33), (-110, 32)])
        gdf = gpd.GeoDataFrame(geometry=[poly], crs="EPSG:4326")
        coords = extract_coordinates(gdf)
        assert len(coords) == 5  # closed ring

    def test_linestring(self):
        line = LineString([(-110, 32), (-109, 33)])
        gdf = gpd.GeoDataFrame(geometry=[line], crs="EPSG:4326")
        coords = extract_coordinates(gdf)
        assert len(coords) == 2

    def test_multilinestring(self):
        mls = MultiLineString([
            [(-110, 32), (-109, 33)],
            [(-108, 34), (-107, 35)],
        ])
        gdf = gpd.GeoDataFrame(geometry=[mls], crs="EPSG:4326")
        coords = extract_coordinates(gdf)
        assert len(coords) == 4


# ---------------------------------------------------------------------------
# geometry_gdf_to_json
# ---------------------------------------------------------------------------


class TestGeometryGdfToJson:
    def test_simple_polygon(self):
        poly = Polygon([(-110, 32), (-109, 32), (-109, 33), (-110, 33), (-110, 32)])
        gdf = gpd.GeoDataFrame(geometry=[poly], crs="EPSG:4326")
        result = geometry_gdf_to_json(gdf)
        assert result["type"] == "Polygon"
        assert "coordinates" in result
        assert len(result["coordinates"][0]) == 5  # closed ring


# ---------------------------------------------------------------------------
# aoi_area_in_km2
# ---------------------------------------------------------------------------


class TestAoiAreaInKm2:
    def test_small_polygon_geojson(self):
        # ~1 degree box near Tucson — roughly 10,000 km²
        geom_json = {
            "type": "Polygon",
            "coordinates": [[
                [-111.0, 32.0], [-110.0, 32.0], [-110.0, 33.0], [-111.0, 33.0], [-111.0, 32.0]
            ]],
        }
        area = aoi_area_in_km2(geom_json)
        assert 9000 < area < 12000

    def test_geodataframe_input(self):
        poly = Polygon([(-111, 32), (-110, 32), (-110, 33), (-111, 33), (-111, 32)])
        gdf = gpd.GeoDataFrame(geometry=[poly], crs="EPSG:4326")
        area = aoi_area_in_km2(gdf)
        assert 9000 < area < 12000

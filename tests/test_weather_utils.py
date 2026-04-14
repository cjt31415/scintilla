"""Tests for scintilla.weather.weather_utils — defensive parsing of messy ISD fields."""

import math

import numpy as np

from scintilla.weather.weather_utils import (
    MAX_REASONABLE_RAINFALL,
    parse_rainfall,
    parse_temp,
)


class TestParseRainfall:
    """ISD AA1 fields are messy in the wild. parse_rainfall must return np.nan
    for anything malformed rather than raising — bulk station downloads will
    encounter all these cases."""

    def test_valid_4_part_qc_1(self):
        # 1 hour, 254 (= 2.54 inches), QC=1 (passed all tests), condition=9
        assert parse_rainfall("01,0254,1,9") == 2.54

    def test_valid_4_part_qc_5(self):
        assert parse_rainfall("01,0100,5,9") == 1.00

    def test_valid_4_part_qc_9(self):
        assert parse_rainfall("01,0050,9,9") == 0.50

    def test_invalid_qc_code_returns_nan(self):
        # QC=2 is not in the allowed set
        assert math.isnan(parse_rainfall("01,0254,2,9"))

    def test_three_part_field_returns_nan(self):
        # The audit's "critical issue #4": malformed AA1 with too few parts
        # used to raise ValueError. Must now return np.nan.
        assert math.isnan(parse_rainfall("01,0254,1"))

    def test_two_part_field_returns_nan(self):
        assert math.isnan(parse_rainfall("01,0254"))

    def test_five_part_field_returns_nan(self):
        assert math.isnan(parse_rainfall("01,0254,1,9,extra"))

    def test_empty_string_returns_nan(self):
        assert math.isnan(parse_rainfall(""))

    def test_nan_input_returns_nan(self):
        assert math.isnan(parse_rainfall(np.nan))

    def test_non_numeric_depth_returns_nan(self):
        assert math.isnan(parse_rainfall("01,XXXX,1,9"))

    def test_excessive_rainfall_returns_nan(self):
        # Anything over MAX_REASONABLE_RAINFALL inches is treated as bad data.
        assert math.isnan(parse_rainfall(f"01,{int((MAX_REASONABLE_RAINFALL + 1) * 100):04d},1,9"))


class TestParseTemp:
    """parse_temp follows the same defensive pattern as parse_rainfall —
    bulk ISD downloads have malformed temperature records and the function
    must return np.nan rather than crash."""

    def test_valid_temp(self):
        # +0153 = 15.3°C, QC=1 (passed)
        assert parse_temp("+0153,1") == 15.3

    def test_negative_temp(self):
        # -0042 = -4.2°C
        assert parse_temp("-0042,1") == -4.2

    def test_invalid_qc_returns_nan(self):
        # QC=2 not in valid set
        assert math.isnan(parse_temp("+0153,2"))

    def test_nan_input_returns_nan(self):
        # The audit's "critical issue": np.nan.split(',') used to AttributeError.
        assert math.isnan(parse_temp(np.nan))

    def test_three_part_field_returns_nan(self):
        assert math.isnan(parse_temp("+0153,1,extra"))

    def test_one_part_field_returns_nan(self):
        assert math.isnan(parse_temp("+0153"))

    def test_empty_string_returns_nan(self):
        assert math.isnan(parse_temp(""))

    def test_non_numeric_value_returns_nan(self):
        assert math.isnan(parse_temp("XXXX,1"))

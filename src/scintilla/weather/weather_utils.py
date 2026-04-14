"""
    weather_utils.py - shared ISD weather data helpers.

    Used by bulk_isd_download.py, download_isd_station_data.py, and
    find_isd_stations_within_aoi.py.
"""
import numpy as np
import pandas as pd
import requests
from shapely.geometry import Point

MAX_REASONABLE_RAINFALL = 6.0


def is_station_within_polygon(station_lat, station_lon, polygon):
    """Return True if (station_lat, station_lon) falls inside `polygon`."""
    return polygon.contains(Point(station_lon, station_lat))


def download_isd_data(usaf, wban, start_date, end_date):
    """Download NOAA ISD hourly observations for one station and date range.

    Returns the parsed JSON list (one record per observation hour). Returns
    an empty list on HTTP failure so callers can pass the result directly to
    pd.DataFrame(...) without a None check. start_date and end_date are
    'YYYY-MM-DD' strings.
    """
    url = (
        "https://www.ncei.noaa.gov/access/services/data/v1"
        f"?dataset=global-hourly&startDate={start_date}&endDate={end_date}"
        f"&stations={usaf}{wban}&format=json"
    )
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    print(f"Failed to retrieve data for station {usaf}{wban}: HTTP {response.status_code}")
    return []


def parse_temp(tmp):
    """Parse ISD temperature field (e.g., '+0153,1') to degrees Celsius.

    Defensive against the same kinds of malformed input that hit parse_rainfall:
    NaN, wrong number of comma-separated parts, non-numeric value. Returns
    np.nan rather than raising.
    """
    if pd.isna(tmp):
        return np.nan

    parts = tmp.split(',')
    if len(parts) != 2:
        return np.nan

    tval, qc_code = parts
    valid_data_codes = ["0", "1", "4", "5", "9"]
    if qc_code not in valid_data_codes:
        return np.nan

    try:
        return int(tval) / 10.0
    except ValueError:
        return np.nan


def celsius_to_fahrenheit(celsius):
    """Convert Celsius to Fahrenheit."""
    return (celsius * 9/5) + 32


def parse_rainfall(aa1_value):
    """Parse ISD AA1 precipitation field to liquid precipitation in inches.

    ISD AA1 fields are messy in the wild — malformed records (wrong number
    of comma-separated parts, non-numeric depth, missing QC codes) appear in
    bulk station downloads. Returns np.nan for anything we can't confidently
    parse rather than raising.
    """
    if pd.isna(aa1_value):
        return np.nan

    parts = aa1_value.split(',')
    if len(parts) != 4:
        return np.nan

    _hours, liq_precip_str, qc_code, _cond_code = parts

    valid_data_codes = ["1", "5", "9"]
    if qc_code not in valid_data_codes:
        return np.nan

    try:
        liq_precip = int(liq_precip_str) / 100.0
    except ValueError:
        return np.nan

    if liq_precip > MAX_REASONABLE_RAINFALL:
        return np.nan

    return liq_precip


def create_rain_windows(df, window_buffer=1, rain_thresh=0.0, window_factor=0.5):
    """Identify rain windows from hourly rainfall data using simple iteration."""
    rainy_days = df['rainfall'] > rain_thresh

    window_starts = []
    window_ends = []
    window_start = None
    window_end = None

    for date, is_rainy in rainy_days.items():
        if is_rainy:
            if window_start is None:
                window_start = date - pd.Timedelta(hours=window_buffer)
            window_end = date + pd.Timedelta(hours=window_buffer)
        else:
            if window_start is not None:
                window_starts.append(window_start)
                window_ends.append(window_end)
                window_start = None
                window_end = None

    if window_start is not None:
        window_starts.append(window_start)
        window_ends.append(window_end)

    rain_windows = pd.DataFrame({'start_date': window_starts, 'end_date': window_ends})

    expansion_time = pd.Timedelta(hours=window_buffer * window_factor)
    rain_windows['start_date'] -= expansion_time
    rain_windows['end_date'] += expansion_time

    rain_windows['total_rainfall'] = rain_windows.apply(
        lambda row: df.loc[row['start_date']:row['end_date'], 'rainfall'].sum(), axis=1)

    return rain_windows



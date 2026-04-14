#!/usr/bin/env python
"""
    map_time.py - support functions for mapping and time conversion

"""
import math
import re
from datetime import UTC, datetime, timedelta

import numpy as np
import pytz
from dateutil.parser import parse
from pyproj import CRS

from scintilla.common.utils import get_utm_epsg_code


def get_utm_epsg_from_gdf(gdf):
    """Return the EPSG code for the UTM zone of the first geometry in `gdf`.

    Thin wrapper around scintilla.common.utils.get_utm_epsg_code: extracts
    a representative (longitude, latitude) point from the first geometry
    (centroid for non-point geoms) and delegates the math.
    """
    if not CRS(gdf.crs).is_geographic:
        raise ValueError("get_utm_epsg_from_gdf expects data in a geographic CRS (WGS84)")
    if gdf.empty:
        raise ValueError("GeoDataFrame is empty")

    first_geometry = gdf.iloc[0].geometry
    if first_geometry is None:
        raise ValueError("First geometry is None")

    if first_geometry.geom_type == 'Point':
        longitude, latitude = first_geometry.x, first_geometry.y
    elif first_geometry.geom_type in ('LineString', 'Polygon', 'MultiPoint', 'MultiLineString', 'MultiPolygon'):
        longitude, latitude = first_geometry.centroid.x, first_geometry.centroid.y
    else:
        raise ValueError(f"Unsupported geometry type: {first_geometry.geom_type}")

    if longitude < -180 or longitude > 180:
        raise ValueError(f"Longitude out of valid range: {longitude}")

    return get_utm_epsg_code(longitude, latitude)


# This function returns a dt + True if given a fully-specified datetime string: '2023-04-05 00:00:00'
# It returns datetime obj, False if given '2023-04-05'
def parse_date_string(date_string):
    time_pattern = re.compile(r'\d{2}:\d{2}(:\d{2})?')
    has_time = bool(time_pattern.search(date_string))
    dt = parse(date_string)
    return dt, has_time


def process_dt_window(ndays, start_date, end_date):

    # switching to more lenient ndays definition 4/7/23
    if ndays:
        end_dt = datetime.now(UTC).replace(tzinfo=None)
        start_of_end_dt = end_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = end_dt.replace(hour=23, minute=59, second=59)
        # Subtract ndays from the current date and time
        delta = timedelta(days=ndays)
        start_dt = (start_of_end_dt - delta).replace(hour=0, minute=0, second=0, microsecond=0)
        num_days = ndays
        #print(f"Assuming you want all of first and last day - rounding down to {start_dt}, up to {end_dt}")
    elif isinstance(start_date, str) and isinstance(end_date, str) and len(start_date) > 0 and len(end_date) > 0:
        start_dt, start_has_time = parse_date_string(start_date)
        end_dt, end_has_time = parse_date_string(end_date)
        assert start_dt < end_dt, "Start datetime must be less than end datetime"
        if not end_has_time:
            end_dt = end_dt.replace(hour=23, minute=59, second=59)
            #print(f"Assuming you want all of last day - rounding up to {end_dt}")
        num_days = (end_dt - start_dt).days
    else:
        num_days = 0
        start_dt = end_dt = None

    return num_days, start_dt, end_dt

#
# convert from UTC time to whatever the local/target timezone is
# input datetime string of the form  "2023.01.19 17:00:00"
# current version is stripping off timezone before return in order
# to store values as-is in database.
# pass in use_naive = False to get datetimes that adjust automatically when stored in DB.
#

def convert_timezone(utc_dt, target_tz_str, use_naive=True):

    if isinstance(utc_dt, str):
        # Parse the UTC datetime string
        utc_dt = datetime.strptime(utc_dt, "%Y.%m.%d %H:%M:%S")

    # Create a timezone object for the target timezone
    target_tz = pytz.timezone(target_tz_str)

    # Convert the UTC datetime to the target timezone
    target_dt = utc_dt.replace(tzinfo=pytz.utc).astimezone(target_tz)

    # remove timezone information
    if use_naive:
        target_dt = target_dt.replace(tzinfo=None)

    return target_dt

#--------------  Mapping functions ---------------------------------


def km_to_miles(km):
    return km * 0.621371

# Define a function to calculate the Haversine distance between two points
def haversine(lat1, lon1, lat2, lon2, return_miles=False):
    # Convert decimal degrees to radians
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat/2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2)**2
    c = 2 * np.arcsin(np.sqrt(a))
    # Radius of earth in kilometers is 6371
    km = 6371 * c

    rval = round(km_to_miles(km), 3) if return_miles else round(km, 3)
    return rval

def bearing_to_cardinal(bearing, return_txt=False):
    cardinals = ['N', 'N-NE', 'NE', 'E-NE', 'E', 'E-SE', 'SE', 'S-SE', 'S', 'S-SW', 'SW', 'W-SW', 'W', 'W-NW', 'NW', 'N-NW', 'N']
    return cardinals[round(bearing / 22.5) % 16]


def bearing(lat1, lon1, lat2, lon2, return_txt=False):
    # Convert latitude and longitude to radians
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    # Calculate the difference between the longitudes
    dlon = lon2 - lon1
    # Calculate the bearing using the Haversine formula
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    bearing = math.degrees(math.atan2(y, x))
    # Normalize the bearing to a value between 0 and 360 degrees
    bearing = round((bearing + 360) % 360, 2)
    bearing = bearing_to_cardinal(bearing) if return_txt else bearing
    return bearing

def parse_location(location_str):
    latitude, longitude = location_str.split(", ")
    latitude_value = float(latitude[:-1])
    longitude_value = float(longitude[:-1])
    if latitude[-1] == "S":
        latitude_value = -latitude_value
    if longitude[-1] == "W":
        longitude_value = -longitude_value
    return latitude_value, longitude_value


def miles_to_km(miles):
    return miles / 0.621371


def km_to_deg(km, lat, is_longitude=False):
    if is_longitude:
        deg_per_km = 1 / (111.111 * math.cos(math.radians(lat)))
    else:
        deg_per_km = 1 / 111.111
    return km * deg_per_km


def make_timezone_aware(dt_obj, tz_id):
    timezone = pytz.timezone(tz_id)
    return timezone.localize(dt_obj)

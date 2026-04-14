#!/usr/bin/env python
"""
    common.py
"""
import json
from datetime import datetime

#from pytz import timezone
from pprint import pprint

import fiona
import geopandas as gpd
import pandas as pd
import pytz
from dateutil.parser import parse
from dateutil.relativedelta import relativedelta
from pyproj import Proj, Transformer
from shapely.geometry import LineString, MultiLineString, Point, Polygon, shape
from shapely.ops import transform

from .defines import (  #, TILE_SIZE, SCENE_DIR, ORDER_URL)
    AOI_DIR,
    LOCAL_TZ,
    MISSION_TO_EARTHDATA_DICT,
    NAN_DATETIME,
)


def geom_total_points(gdf):
    coords = extract_coordinates(gdf)
    return len(coords)



def load_geopackage_layer(file_path, layer_name):
    geodataframe = gpd.read_file(file_path, layer=layer_name)
    return geodataframe



def load_geopackage_all_layers(file_path):
    """
    Read all layers from a GeoPackage into a single GeoDataFrame.

    Parameters:
        file_path (str): Path to the GeoPackage file.

    Returns:
        GeoDataFrame: A GeoDataFrame containing all layers.
    """
    # List all layer names in the GeoPackage
    layer_names = fiona.listlayers(file_path)

    # Read each layer into a GeoDataFrame and store them in a list
    gdf_list = [gpd.read_file(file_path, layer=layer) for layer in layer_names]

    # Concatenate all the GeoDataFrames into a single GeoDataFrame
    all_layers_gdf = gpd.GeoDataFrame(pd.concat(gdf_list, ignore_index=True))

    return all_layers_gdf


def list_layers_in_geopackage(file_path, debug=False):
    layers = fiona.listlayers(file_path)
    if debug:
        print(f"Geopackage {file_path} layers:")
        pprint(layers)
    return layers


def check_layer_name(file_path, layer_name):
    layers = fiona.listlayers(file_path)
    if layer_name not in layers:
        available = ", ".join(layers)
        raise ValueError(f"Layer '{layer_name}' not found in {file_path}. Available: {available}")

# take two datetime objects and advance by one month
def iterate_over_months(start_date, end_date):
    current_date = start_date
    while current_date <= end_date:
        yield current_date
        current_date += relativedelta(months=+1)


# Helper function to printformatted JSON using the json module
def pjson(data):
    print(json.dumps(data, indent=2))


def load_json_data(fpath):
    assert fpath.is_file(), f"Did not find json file: {fpath}"

    with open(fpath) as json_file:
        data = json.load(json_file)
    return data


def read_geojson(geojson_path):
    return gpd.read_file(geojson_path)


def load_geometry(name):
    full_path = AOI_DIR / f"{name}_aoi.geojson"
    if not full_path.exists():
        raise FileNotFoundError(f"AOI geometry not found for AOI [{name}] at {full_path}")

    geom = read_geojson(full_path)
    return geom



def aoi_list():
    """Return sorted AOI names discovered under AOI_DIR.

    Each AOI is a `<name>_aoi.geojson` file in `data/aois/`. Files that
    don't end in `_aoi` are skipped with a warning.

    If `AOI_DIR` doesn't exist, prints a clear warning and returns []. The
    empty result is what `argparse choices=aoi_list()` is going to see at
    module-load time on a fresh checkout — better that than the silent
    "no valid choices" behavior the previous glob-on-missing-dir produced.
    """
    if not AOI_DIR.exists():
        print(f"Warning: AOI_DIR does not exist: {AOI_DIR}")
        return []

    aoi_paths = list(AOI_DIR.glob("*.geojson"))
    aoi_stems = [aoi.stem for aoi in aoi_paths]

    valid_aoi_stems = []
    for aoi_stem in aoi_stems:
        if aoi_stem.endswith('_aoi'):
            valid_aoi_stems.append(aoi_stem)
        else:
            print(f"Badly formed AOI name: {aoi_stem}")

    aoi_names = [aoi_stem[:-len('_aoi')] for aoi_stem in valid_aoi_stems]
    return sorted(aoi_names)


# returns [west, south, east, north]
# this is the mercantile.Bbox(left, bottom, right, top) format!
def polygon_to_bbox(aoi_geom):
    # [-122.0734289598223, 38.50143514531866, -122.04737617792237, 38.519772350963365]

    # set up the starting values to find min and max for 4 coords
    west = 180
    east = -180
    north = -90
    south = 90

    # coordinates is a list of lists of pairs [lon, lat]
    # 'coordinates': [[[-111.06407084814117, 32.29678902025716], ...]]
    for coord_pair in aoi_geom['coordinates'][0]:
        west = min(west, coord_pair[0])
        east = max(east, coord_pair[0])
        north = max(north, coord_pair[1])
        south = min(south, coord_pair[1])

    return [west, south, east, north]


def geometry_gdf_to_json(gdf):
    boundary_geometry = gdf.geometry.boundary
    boundary_points = boundary_geometry.apply(lambda geom: list(geom.coords))

    coords = boundary_points.iloc[0]

    context = {'type': 'Polygon', 'coordinates': [coords]}
    return context

def utm_polygon(geom_json):

    assert isinstance(geom_json, dict), "Expected a dict"
    assert 'coordinates' in geom_json, "Expected to find 'coordinates' in geom_json"

    # Extract the longitude of the first point of the polygon
    lon = geom_json['coordinates'][0][0][0]

    # Calculate the UTM zone dynamically
    utm_zone = int((lon + 180) / 6) + 1

    # Define projections
    in_proj = Proj(proj='latlong', datum='WGS84')
    out_proj = Proj(proj='utm', zone=utm_zone, datum='WGS84')

    # Create transformer
    transformer = Transformer.from_proj(in_proj, out_proj)

    # Create a shapely polygon from the GeoJSON geometry
    polygon = shape(geom_json)

    # Reproject the polygon to UTM coordinates to get accurate measurements
    polygon_utm = transform(transformer.transform, polygon)

    return polygon_utm



def get_utm_epsg_code(longitude, latitude):
    """Return the EPSG code for the UTM zone containing (longitude, latitude).

    Returns a string like '32612' for UTM 12N or '32734' for UTM 34S.
    Wraps via modulo so that longitude == 180.0 returns zone 1 (the canonical
    convention) rather than the invalid zone 61.
    """
    utm_zone_number = int((longitude + 180) / 6) % 60 + 1
    epsg_prefix = "326" if latitude >= 0 else "327"
    return f"{epsg_prefix}{utm_zone_number}"


def extract_coordinates(geodataframe):
    all_coords = []

    for geom in geodataframe.geometry:
        if isinstance(geom, LineString):
            # there are some geometries that have elevation (x, y, z)
            for tpl in geom.coords:
                all_coords.append((tpl[1], tpl[0]))  # Latitude, Longitude
        elif isinstance(geom, Polygon):
            for x, y in geom.exterior.coords:   # note how exterior is needed
                all_coords.append((y, x))  # Latitude, Longitude
        elif isinstance(geom, MultiLineString):
            # for line in geom:
            #     for x, y in line.coords:
            #         all_coords.append((y, x))  # Latitude, Longitude
            # iterate over the geoms first
            for line in geom.geoms:
                for x, y in line.coords:
                    all_coords.append((y, x))  # Latitude, Longitud
        elif isinstance(geom, Point):
            x, y = geom.coords[0]
            all_coords.append((y, x))  # Latitude, Longitude

    return all_coords


# apply a buffer of min_distance meters around all geometries in gdf
# return buffered gdf
def buffer_gdf(gdf, min_distance):

    assert gdf.crs == 'EPSG:4326', "buffer_gdf expects data in WGS84"

    #gdf.to_file(f"gdf_debug_{round(min_distance, 2)}.gpkg", layer='before', driver="GPKG")

    first_geometry = gdf.iloc[0].geometry

    # Check the type of the geometry and get a longitude value
    if first_geometry.geom_type == 'Point':
        longitude = first_geometry.x
        latitude = first_geometry.y
    elif first_geometry.geom_type in ['LineString', 'Polygon']:
        # Using centroid for simplicity. Other methods may be more appropriate depending on your data
        longitude = first_geometry.centroid.x
        latitude = first_geometry.centroid.y
    else:
        raise ValueError("Unsupported geometry type")

    # Calculate the UTM zone dynamically
    int((longitude + 180) / 6) + 1

    epsg_code = get_utm_epsg_code(longitude, latitude)

    gdf_projected = gdf.to_crs(epsg=epsg_code)
    # Step 2: Apply the buffer in meters in the projected CRS
    gdf_projected['geometry'] = gdf_projected.geometry.buffer(min_distance)

    # Step 3 (Optional): Reproject back to the original CRS if needed
    gdf_buffered = gdf_projected.to_crs(gdf.crs)

    #gdf_buffered.to_file(f"gdf_debug_{round(min_distance, 2)}.gpkg", layer='after', driver="GPKG")

    return gdf_buffered

# this is a better UTM zone finder - it uses both longitude zone number
# and latitude band character, generating zones like 12S
def get_utm_zone(lat, lon):
    # Calculate UTM zone number
    zone_number = int((lon + 180) / 6) + 1

    # Determine the latitudinal band
    if lat < -80:
        band = 'C'
    elif lat > 84:
        band = 'X'
    else:
        band = chr(int((lat + 80) / 8) + ord('C'))

    # Combine zone number and band
    return f"{zone_number}{band}"


# why does this work, when the naive gdf.area computations do not?
# Using a dynamic UTM zone calculation ensures that area measurements are
# consistent and accurate, even if the user requests data from regions that
# span multiple UTM zones. This adaptability is crucial for a service like Planet's,
# which provides satellite imagery and geospatial data for diverse global applications.
#
# By dynamically determining the UTM zone and reprojecting the data as needed,
# the service can offer users accurate geospatial information, regardless of the
# location they are interested in. It's a good practice for global geospatial data
# providers to handle various coordinate systems and projections to accommodate a
# wide range of user needs and geographic locations.

# allow this to be called with either a geopandas dataframe or a simplified geojson dict
def aoi_area_in_km2(geom_json_or_gdf):

    if isinstance(geom_json_or_gdf, gpd.geodataframe.GeoDataFrame):
        gdf = geom_json_or_gdf
        if len(gdf) > 1:
            gdf = gdf.dissolve()
        polygon = gdf.geometry.iloc[0]   # shapely Polygon or MultiPolygon
    else:
        polygon = shape(geom_json_or_gdf)

    #lon = geom_json['coordinates'][0][0][0]

    # Extract the longitude of the first point of the polygon
    #lon = coords[0][0]

    # Calculate the UTM zone dynamically
    # utm_zone = int((lon + 180) / 6) + 1

    centroid = polygon.centroid
    lat, lon = centroid.y, centroid.x

    full_utm_zone = get_utm_zone(lat, lon) # e.g. 21L
    utm_zone = int(full_utm_zone[:-1])  # just the integer for pyproj

    # Define projections
    in_proj = Proj(proj='latlong', datum='WGS84')
    out_proj = Proj(proj='utm', zone=utm_zone, datum='WGS84')

    # Create transformer
    transformer = Transformer.from_proj(in_proj, out_proj)


    # Reproject the polygon to UTM coordinates to get accurate measurements
    polygon_utm = transform(transformer.transform, polygon)

    # Calculate the area in square meters
    area_m2 = polygon_utm.area

    # Convert to square kilometers
    area_km2 = area_m2 / 1e6

    return area_km2


def confirm(prompt=None, resp=False):
    """Prompts for yes or no response from the user. Returns True for yes and
    False for no.

    'resp' should be set to the default value assumed by the caller when
    user simply types ENTER.
    """

    if prompt is None:
        prompt = 'Confirm'

    if resp:
        prompt = f'{prompt} [Y/n]: '
    else:
        prompt = f'{prompt} [y/N]: '

    while True:
        ans = input(prompt)
        if not ans:
            return resp
        if ans.lower() not in ['y', 'n']:
            print('Please enter y or n.')
            continue
        if ans.lower() == 'y':
            return True
        if ans.lower() == 'n':
            return False

def convert_to_utc(local_datetime, local_timezone):
    """
    Convert a timezone-aware datetime object to UTC.

    :param local_datetime: a timezone-aware datetime object
    :param local_timezone: string representation of the local timezone
    :return: UTC datetime object
    """
    local_tz = pytz.timezone(local_timezone)
    local_dt = local_tz.localize(local_datetime)
    utc_dt = local_dt.astimezone(pytz.timezone('UTC'))
    return utc_dt



def get_aoi_timezone(aoi_name):
    """Get the IANA timezone for an AOI based on its centroid.

    Uses timezonefinder to look up timezone from the AOI polygon's centroid.
    Returns timezone string (e.g., 'America/Phoenix', 'America/New_York').
    """
    import warnings

    from timezonefinder import TimezoneFinder

    gdf = load_geometry(aoi_name)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        centroid = gdf.geometry.centroid.iloc[0]
    tf = TimezoneFinder()
    tz = tf.timezone_at(lat=centroid.y, lng=centroid.x)
    return tz or 'UTC'


def parse_date_range(start_date, end_date, aoi=None, utc=False):
    """Parse start/end date strings from CLI, converting to UTC.

    If utc=True: dates are already in UTC, no conversion needed.
    If utc=False: dates are in the AOI's local timezone (looked up from centroid).
    Falls back to US/Arizona if no AOI provided.

    Returns (start_dt_utc, end_dt_utc, local_tz_str).
    Both datetimes are timezone-aware UTC.
    """
    start_dt = parse(start_date)
    end_dt = parse(end_date) if end_date else datetime.now()

    if utc:
        local_tz_str = 'UTC'
        start_dt_utc = pytz.utc.localize(start_dt) if start_dt.tzinfo is None else start_dt.astimezone(pytz.utc)
        end_dt_utc = pytz.utc.localize(end_dt) if end_dt.tzinfo is None else end_dt.astimezone(pytz.utc)
    else:
        local_tz_str = get_aoi_timezone(aoi) if aoi else 'US/Arizona'
        start_dt_utc = convert_to_utc(start_dt, local_tz_str)
        end_dt_utc = convert_to_utc(end_dt, local_tz_str)

    return start_dt_utc, end_dt_utc, local_tz_str


def format_time_display(utc_dt, local_tz_str):
    """Format a UTC datetime for user display showing both local and UTC.

    Example: '2023-07-30 21:15 MST (04:15 UTC)'
    """
    local_tz = pytz.timezone(local_tz_str)
    local_dt = utc_dt.astimezone(local_tz)
    tz_abbr = local_dt.strftime('%Z')
    utc_str = utc_dt.strftime('%H:%M UTC')
    local_str = local_dt.strftime('%Y-%m-%d %H:%M')
    return f"{local_str} {tz_abbr} ({utc_str})"


def format_time_short(utc_dt, local_tz_str):
    """Format a UTC datetime as short local time for frame timestamps.

    Example: '2023-07-30 21:15 MST'
    """
    local_tz = pytz.timezone(local_tz_str)
    local_dt = utc_dt.astimezone(local_tz)
    tz_abbr = local_dt.strftime('%Z')
    return f"{local_dt.strftime('%Y-%m-%d %H:%M')} {tz_abbr}"


def format_utc_to_string(utc_datetime):
    """
    Format a UTC datetime object to a string in the format: "YYYY-MM-DDTHH:MM:SS.sssZ"

    :param utc_datetime: timezone-aware UTC datetime object
    :return: formatted string
    """
    return utc_datetime.strftime('%Y-%m-%d %H:%M:%S') + 'Z'
    # return utc_datetime.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'



def find_timespan(collection):
    earliest_date = convert_to_utc(NAN_DATETIME, LOCAL_TZ)

    if "TemporalExtents" not in collection['umm']:
        return earliest_date, earliest_date

    # find the earliest start_date
    start_date = convert_to_utc(datetime.now(), LOCAL_TZ)

    for daterange in collection['umm']["TemporalExtents"]:
        for tempext in daterange["RangeDateTimes"]:
            dt = parse(tempext["BeginningDateTime"])
            if dt < start_date:
                start_date = dt

    # find the most recent end date
    end_date = convert_to_utc(NAN_DATETIME, LOCAL_TZ)
    for daterange in collection['umm']["TemporalExtents"]:
        if "EndsAtPresentFlag" in daterange and daterange["EndsAtPresentFlag"]:
            end_date = convert_to_utc(datetime.now(), LOCAL_TZ)
            break

        for tempext in daterange["RangeDateTimes"]:
            try:
                dt = parse(tempext["EndingDateTime"])   # some records only have start date
            except (KeyError, ValueError):
                dt = convert_to_utc(datetime.now(), LOCAL_TZ)   # on exception just assume it doesn't end
            if dt > end_date:
                end_date = dt

    return start_date, end_date


def mission_data(mission):
    if mission not in MISSION_TO_EARTHDATA_DICT:
        raise ValueError(
            f"mission {mission} not found in MISSION_TO_EARTHDATA_DICT "
            f"{list(MISSION_TO_EARTHDATA_DICT.keys())}"
        )
    return MISSION_TO_EARTHDATA_DICT[mission]


def reverse_polygon_order(polygon):
    # Check if the last point is the same as the first point
    if polygon[0] == polygon[-1]:
        # Remove the last point to avoid duplicates
        polygon.pop()

    # Reverse the order of the points
    reversed_polygon = polygon[::-1]

    # Add the first point to the end to close the polygon
    reversed_polygon.append(reversed_polygon[0])

    return reversed_polygon


def parse_julian_date_from_path(filename):
    # Split the path by underscores and filter for the part that starts with 's'
    date_part = [part for part in filename.split('_') if part.startswith('s')][0]

    # Extract the date and time parts after 's'
    # The format after 's' is: YYYYDDDHHMMSS??
    # e.g. 'OR_GLM-L3-GLMF-M6_G18_s202323215130000_e202323215140000_c20232321514540.nc'
    julian_str = date_part[1:-2]  # Remove the 's' and the last two 0's

    # Parse the date and time
    date_time = datetime.strptime(julian_str, '%Y%j%H%M%S')

    # Make the datetime object timezone-aware by setting it to UTC
    date_time = date_time.replace(tzinfo=pytz.utc)

    return date_time


def find_files(goes_dir, start_dt_utc, end_dt_utc, ext='nc', return_by='list'):

    search_str = f"**/*.{ext}"
    path_list = list(goes_dir.rglob(search_str))

    # generate the datetime obj for each file, skipping malformed names
    # rather than aborting the whole scan on the first ValueError.
    path_dict_list = []
    skipped = 0
    for path in path_list:
        try:
            dt = parse_julian_date_from_path(path.name)
        except (ValueError, IndexError) as e:
            print(f"  skipping unparseable filename {path.name}: {type(e).__name__}: {e}")
            skipped += 1
            continue
        path_dict_list.append({'dt': dt, 'path': path})

    if skipped:
        print(f"  find_files: skipped {skipped} of {len(path_list)} files with unparseable names")

    # filter the paths using dates
    filtered_dict_list = [pdict for pdict in path_dict_list if pdict['dt'] >= start_dt_utc and pdict['dt'] < end_dt_utc]

    if return_by == 'list':
        filtered_path_list = [pdict['path'] for pdict in filtered_dict_list]
        sorted_path_list = sorted(filtered_path_list)
        return sorted_path_list
    elif return_by == 'dict':
        sorted_dict_list = sorted(filtered_dict_list, key=lambda d: d['dt'])
        return sorted_dict_list


STATE_ABBR_DICT = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
    "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY"
}

def state_abbr(state_name):
    if state_name not in STATE_ABBR_DICT:
        raise ValueError(f"{state_name} not found in STATE_ABBR_DICT")

    return STATE_ABBR_DICT[state_name]

def clean_state_name(state_name):
    name = state_name.lower()
    name = name.replace(" ", "_")
    return name

def validate_state_name(us_state_borders_gdf, state):
    """Case-insensitive state lookup. Returns the canonical-cased name from
    the shapefile (e.g. "new mexico" → "New Mexico"). Raises on no match."""
    all_states = sorted(us_state_borders_gdf['NAME'].unique())
    lookup = {s.lower(): s for s in all_states}
    canonical = lookup.get(state.lower())
    if canonical is not None:
        return canonical

    available = ", ".join(all_states)
    raise ValueError(f"State '{state}' not found. Available: {available}")


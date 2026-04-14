#!/usr/bin/env python
"""
    defines.py: key directories, URLs, constants
"""

import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (walks up from this file to find it)
_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env")

ISD_HISTORY_URL = "https://www1.ncdc.noaa.gov/pub/data/noaa/isd-history.csv"

# Data directory root. In order of precedence:
#   1. SCINTILLA_DATA_DIR environment variable (absolute or relative to CWD)
#   2. ./data relative to the repo root (the public-repo demo layout)
DATA_DIR = Path(os.environ.get("SCINTILLA_DATA_DIR", _REPO_ROOT / "data"))
METADATA_DIR = DATA_DIR / "metadata"
AOI_DIR = DATA_DIR / "aois"
GIS_DIR = DATA_DIR / "gis"
ISD_WEATHER_DIR = DATA_DIR / "weather"

GLM_RAW_DIR = DATA_DIR / "glm_raw"
GLM_CLIP_DIR = DATA_DIR / "glm_clips"
GLM_POLYGON_DIR = DATA_DIR / "glm_polygons"
ISSLIS_RAW_DIR = DATA_DIR / "isslis"
GEDI_RAW_DIR = DATA_DIR / "gedi"

GRANULE_METADATA_DIR = DATA_DIR / "granule_metadata"


GEOGRAPHIC_CRS = 4326
WEB_MERCATOR_CRS = 3857

LOCAL_TZ = 'US/Pacific'

MAX_CLOUD_COVER = 0.95

TILE_SIZE = 256 	# for basemaps and scene tiles

NAN_DATETIME = datetime(1970, 1, 1, 0, 0, 0)    # Linux start of epoch

# content of this table obtained semi-manually from running search_collections.py
# first by keyword, then short-name
# provider_id hand located using search_collection.py --short-name glmgoesL3
# GLM netCDF variable layout (GOES-R Series Lightning Mapper L2/L3 grids).
# Order matches the variable order in the source .nc files.
GLM_VARIABLES = ['x', 'y', 'Flash_extent_density', 'Total_Optical_energy', 'Minimum_flash_area', 'DQF', 'goes_imager_projection']
GLM_VARIABLE_ABBR = ['X', 'Y', 'FED', 'TOE', 'MFA', 'DQF', 'GIP']
TOE_IDX = GLM_VARIABLES.index('Total_Optical_energy')

MISSION_TO_EARTHDATA_DICT = {
    'GEDI': {'short_name': 'GEDI02_B', 'daac': "LP", 'provider_id': "LPDAAC_ECS", 'version': "002"},               # 96 variables
    'GEDI02_A': {'short_name': 'GEDI02_A', 'daac': "LP", 'provider_id': "LPDAAC_ECS", 'version': '002'},           # 156 variables
    'ISSLIS': {'short_name': 'isslis_v3_fin', 'daac': "GHRC", 'provider_id': "GHRC_DAAC", 'version': "3"},
    'ISSLIS-V2': {'short_name': 'isslis_v2_fin', 'daac': "GHRC", 'provider_id': "GHRC_DAAC", 'version': "2"},      # older reprocessing; existing 2020+ files on disk are V2.1
    'ISSLIS-B': {'short_name': 'isslisg_v2_fin', 'daac': "GHRC", 'provider_id': "GHRC_DAAC", 'version': "2"},      # ISS LIS background dataset
    'GLM': {'short_name': 'glmgoesL3', 'daac': "GHRC", 'provider_id': "GHRC_DAAC", 'version': "001"}
}

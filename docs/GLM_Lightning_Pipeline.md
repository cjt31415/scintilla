# GLM Lightning Detection and Visualization Pipeline

## Overview

This project is a Python-based pipeline for downloading, processing, and visualizing lightning data from NASA's Geostationary Lightning Mapper (GLM) instrument aboard the GOES-R series satellites. The pipeline correlates lightning activity with ground-based weather station data and produces animated map visualizations showing lightning events over time.

The system also supports two additional NASA datasets (GEDI lidar and ISS LIS lightning), but the GLM lightning animation workflow is the most developed and exercised pipeline.

---

## Data Sources

### GLM (Geostationary Lightning Mapper)
- **Instrument:** Optical sensor on GOES-16/17/18 geostationary satellites
- **Coverage:** Continuous, full-disk (Western Hemisphere) from geostationary orbit
- **Temporal resolution:** 20-second scan intervals, aggregated into ~1-minute Level 3 products
- **Spatial resolution:** ~8 km at nadir
- **Data format:** NetCDF4 (`.nc`)
- **Key variables used:**
  - `Total_Optical_energy` (TOE) -- primary variable used for chip cutting and visualization
  - `Flash_extent_density` (FED)
  - `Minimum_flash_area` (MFA)
- **EarthData short_name:** `glmgoesL3`, provider: `GHRC_DAAC`
- **Current default satellite:** GOES-18 (G18)

### ISD (Integrated Surface Database) Weather Stations
- **Source:** NOAA NCEI hourly weather observations
- **Purpose:** Identify rain windows to correlate with lightning activity
- **API:** `https://www.ncei.noaa.gov/access/services/data/v1`
- **Report types used:** FM-12 (SYNOP) and FM-15 (METAR)
- **Derived product:** "Rain windows" -- time intervals with detected precipitation, used to guide GLM data downloads

### ISS LIS (International Space Station Lightning Imaging Sensor)
- **Low-Earth orbit lightning sensor (mission ended December 2023)**
- **Point-based flash data (lat/lon) rather than gridded imagery**
- **EarthData short_name:** `isslis_v2_fin`, provider: `GHRC_DAAC`

---

## Pipeline Architecture

### Directory Structure

```
/opt/scintilla/
├── src/scintilla/       # Installable Python package
│   ├── common/          # Shared utilities (geometry, dates, constants, mapping)
│   ├── tools/           # Data pipeline scripts (search, download, cut, polygonize)
│   ├── animate/         # Map animation and movie generation
│   └── weather/         # ISD weather station data acquisition
├── data/
│   ├── aois/            # GeoJSON area-of-interest definitions (*_aoi.geojson)
│   ├── metadata/        # Station lists, ISD metadata
│   ├── weather/         # Downloaded weather station data and rain windows
│   ├── granule_metadata/# CSV files mapping granule URLs to time ranges
│   ├── glm_raw/         # Raw NetCDF files organized by satellite/year/month/day
│   ├── glm_clips/       # AOI-clipped GeoTIFFs organized by AOI/year/month/day
│   ├── glm_polygons/    # Vectorized lightning polygons in GeoPackage format
│   ├── isslis/          # Raw ISS LIS NetCDF files
│   ├── isslis_clips/    # AOI-clipped ISS LIS flash data
│   ├── gis/             # Reference GIS data (US state boundaries)
│   └── movies/          # Final MP4 animations
├── tests/               # pytest test suite
├── docs/                # Reference documentation
├── pyproject.toml       # Package metadata + dependencies
└── justfile             # Task runner
```

### Shared Modules (`src/scintilla/common/`)

| Module | Purpose |
|--------|---------|
| `defines.py` | Path constants, mission-to-EarthData lookup table, CRS constants, timezone, .env loading |
| `utils.py` | AOI loading, geometry operations, UTM projection, date parsing, bbox calculation |
| `map_utils.py` | Cartopy tile provider factory (Google, OSM, Stadia), degrees-to-meters conversion |
| `map_time.py` | Timezone conversion, haversine distance, bearing, km-to-degrees |
| `my_logging.py` | Logging configuration with LocalTimeFormatter for GPU servers |

---

## Pipeline Steps (End-to-End)

### Step 1: Weather Station Discovery

**Script:** `src/scintilla/weather/download_master_isd_stations_list.py`

Downloads the global ISD station catalog from NOAA. This is a one-time operation.

**Output:** `data/metadata/isd_station_metadata.csv`

---

### Step 2: Find Stations Within Area of Interest

**Script:** `src/scintilla/weather/find_isd_stations_within_aoi.py`

```bash
cd src/scintilla/weather
./find_isd_stations_within_aoi.py --aoi southwest
```

Filters the global station list to those within a given AOI polygon. The user then manually curates the results into a metadata file (e.g., `data/metadata/southwest_isd_stations.csv`) with columns: `name`, `isd_name`, `notes`.

---

### Step 3: Download Weather Data and Identify Rain Windows

**Script:** `src/scintilla/weather/bulk_isd_download.py`

```bash
cd src/scintilla/weather
./bulk_isd_download.py --aoi tucson --start-date 2023-01-01 --end-date 2023-12-31 --save-raw-csv
```

For each curated station:
1. Downloads hourly weather observations via NOAA API
2. Parses temperature (`TMP` field) and rainfall (`AA1` field) with quality-code filtering
3. Identifies "rain windows" -- contiguous periods of precipitation with configurable buffer and threshold
4. Generates per-station rainfall plots and a merged cross-station visualization

**Outputs:**
- `data/weather/<aoi>/<station>_raw_<dates>.csv` -- raw hourly observations
- `data/weather/<aoi>/<station>_rainwin_<dates>.csv` -- detected rain windows

**Known issue:** The rain-window merging can produce overlapping windows, leading to duplicate granule downloads in the next step. The workaround is to use `get_granules.py` with a simple date range instead of `get_rain_window_granules.py`.

---

### Step 4: Search for GLM Granules

**Script:** `src/scintilla/tools/get_granules.py`

```bash
cd src/scintilla/tools
./get_granules.py --aoi tucson --start-date 2023-12-20 --end-date 2023-12-25 --mission GLM --max-items 15000
```

Uses `earthaccess` to query NASA's CMR (Common Metadata Repository) for matching granules. Authentication is via `~/.netrc` (NASA EarthData credentials).

For GLM specifically, results are filtered to a single satellite (default: G18) to avoid duplicate coverage from G16/G17/G18 overlap.

**Output:** `data/granule_metadata/<aoi>/GLM_<aoi>_<start>_<end>.csv` with columns: `begin_dt`, `end_dt`, `url`, `s3url`

---

### Step 5: Download Raw NetCDF Files

**Script:** `src/scintilla/tools/download_from_urls.py`

```bash
cd src/scintilla/tools
./download_from_urls.py --aoi tucson --start-date 2023-12-20 --end-date 2023-12-25 --max-items 2 --mission GLM
```

Reads the granule CSV from Step 4 and downloads each file via authenticated HTTPS (using `earthaccess.get_fsspec_https_session()`). Includes retry logic (5 retries, 10-second delay). Skips previously downloaded files.

**Output:** `data/glm_raw/G18/<year>/<month>/<day>/*.nc`

**Note:** S3 direct-access download is partially implemented but not yet working.

---

### Step 6: Cut AOI Chips from Raw Data

**Script:** `src/scintilla/tools/cut_glm_aoi_chips.py`

```bash
cd src/scintilla/tools
./cut_glm_aoi_chips.py --aoi bayarea --start-date 2023-08-20 --end-date 2023-08-25 --goes-satellite G18 --max-items 10000
```

For each raw NetCDF file:
1. Opens with `rioxarray` using the `Total_Optical_energy` variable
2. Reprojects the AOI polygon from WGS84 to the GOES-R geostationary projection
3. Clips the raster to the reprojected AOI
4. Saves as a single-band GeoTIFF

**Output:** `data/glm_clips/<aoi>/<year>/<month>/<day>/TOE_<original_stem>.tif`

There is also `cut_glm_state_chips.py` which clips by US state boundary instead of a custom AOI polygon.

---

### Step 7 (Optional): Sum Chips for Quick Inspection

**Script:** `src/scintilla/tools/sum_glm_chips.py`

```bash
cd src/scintilla/tools
./sum_glm_chips.py --aoi florida --start-date 2023-08-20 --end-date 2023-08-25
```

Stacks all GeoTIFFs for the date range and sums pixel values to produce a single cumulative-lightning image. Useful for verifying that lightning data exists in the AOI before committing to the full animation pipeline.

**Output:** `data/glm_clips/<aoi>/<aoi>_clip_sum.tif`

**Important:** This sum file must be deleted before running `movie_map.py`, as it breaks the frame selection logic.

---

### Step 8 (Optional): Convert Raster Chips to Vector Polygons

**Script:** `src/scintilla/tools/chips_to_polygons.py`

```bash
cd src/scintilla/tools
./chips_to_polygons.py --state Arizona --start-date 2023-07-16 --end-date 2023-07-19 --chunk-size hour --polygon-type pixel
```

Converts raster lightning data into vector polygons with three strategies:
- **`pixel`**: Each non-zero pixel becomes a rectangular polygon with its TOE value
- **`connected`**: Connected components are merged into convex hulls with aggregated mean/max/sum TOE
- **`uniform`**: Groups pixels by identical TOE values into contour polygons (partially implemented, includes `cv2.waitKey` debug calls)

Results are grouped by configurable time chunks (`all`, `week`, `day`, `hour`, `minute`) and stored as layers in a GeoPackage.

**Output:** `data/glm_polygons/<region>/<region>_<type>_<dates>[_<chunk>].gpkg`

---

### Step 9: Generate Animation

**Scripts:** `src/scintilla/animate/movie_map.py` (orchestrator) + `src/scintilla/animate/movie_frame_map.py` (per-frame rendering)

```bash
cd src/scintilla/animate
./movie_map.py --aoi florida --start-date 2023-08-20 --end-date 2023-08-25
```

The animation pipeline:
1. Loads the AOI geometry or US state boundary to determine map extent
2. Calculates an appropriate zoom level based on area
3. Fetches a background map image (Google Tiles, OSM, Stamen, or white) via cartopy at the calculated zoom
4. Iterates through time using `--delta-t` (minutes between frames) and `--window-t` (minutes of data visible per frame)
5. For each frame, overlays the GLM raster chip onto the background map using rasterio + cartopy
6. Saves frames as JPEG to `/tmp/ffmpeg/`
7. Encodes all frames into an MP4 using ffmpeg-python

**Key parameters:**
- `--delta-t`: Time step between frames (default: 1 minute)
- `--window-t`: Width of the sliding time window shown per frame (default: 360 minutes / 6 hours)
- `--framerate`: Frames per second in output video (default: 4)
- `--background`: Map tile provider (`google`, `osm`, `terrain-background`, `none`)

**Output:** `data/movies/<region>_<start>_<end>.mp4` (or `.gif` with `--output-format gif`)

---

## AOI Management

Areas of interest are stored as GeoJSON files in `data/aois/` following the naming convention `<name>_aoi.geojson`. Example AOIs include geographic regions (florida, arizona, bayarea), cities (tucson, houston-area), and international locations (catatumbo, porto-alegra).

The renderer respects the AOI's actual aspect ratio — output dimensions are derived from the AOI bbox at render time. If you want to commit to a specific aspect (e.g., 16:9 for YouTube, 1:1 for a square thumbnail), the utility `src/scintilla/tools/aoi_snap_aspect.py --aspect W:H` snaps an arbitrary AOI polygon to the target ratio.

---

## Authentication

All NASA EarthData access requires credentials stored in `~/.netrc`:
```
machine urs.earthdata.nasa.gov login <username> password <password>
```

The pipeline uses `earthaccess.login(strategy="netrc", persist=True)` for authentication.

---

## Key Dependencies

| Package | Purpose |
|---------|---------|
| `earthaccess` | NASA EarthData authentication and CMR granule search |
| `xarray` + `rioxarray` | NetCDF reading with geospatial-aware clipping |
| `rasterio` | GeoTIFF I/O and CRS transformation |
| `netCDF4` | Low-level NetCDF variable inspection |
| `geopandas` + `shapely` + `fiona` | Vector geometry operations and GeoPackage I/O |
| `cartopy` | Map projections and tile-based backgrounds |
| `ffmpeg-python` | Video encoding from frame sequences |
| `cv2` (OpenCV) | Connected component analysis for polygon extraction |
| `pyproj` | CRS transformations and UTM zone calculation |
| `joblib` | Parallel frame rendering (currently disabled) |
| `pandas` | Tabular data throughout the pipeline |

---

## Current Limitations and Known Issues

1. **S3 direct access** is partially coded but not functional -- all downloads use HTTPS
2. **Rain window overlap bug** in `bulk_isd_download.py` can produce duplicate granules; workaround is using `get_granules.py` with a flat date range
3. **`sum_glm_chips.py` output file** must be manually deleted before running `movie_map.py`
4. **Parallel rendering** in `movie_map.py` is not implemented; sequential rendering works but is slow for long time series

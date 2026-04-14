#!/usr/bin/env python
"""
    cut_glm_aoi_chips.py - read .nc files, cut to AOI, output geotiff

    Guts of processing from:
    https://github.com/daniellelosos/GOES-R_NetCDF_to_GeoTIFF/blob/main/Clip%20with%20Shapefile.ipynb

"""

import argparse
from datetime import datetime

import geopandas as gpd
import rioxarray
from shapely.geometry import mapping

from scintilla.common.defines import (
    GLM_CLIP_DIR,
    GLM_RAW_DIR,
    GLM_VARIABLE_ABBR,
    GLM_VARIABLES,
    TOE_IDX,
)
from scintilla.common.utils import (
    aoi_area_in_km2,
    aoi_list,
    find_files,
    format_time_display,
    load_geometry,
    parse_date_range,
)


def ensure_chips(
        out_name: str,
        clip_gdf: gpd.GeoDataFrame,
        start_dt_utc: datetime,
        end_dt_utc: datetime,
        goes_satellite: str = 'G18',
        max_items: int | None = None,
        verbose: bool = True) -> dict:
    """Clip any raw GLM .nc files in [start_dt_utc, end_dt_utc) that don't
    already have corresponding .tif chips under GLM_CLIP_DIR/<out_name>/.

    `clip_gdf` is the geometry to clip against. Multi-row inputs (e.g. several
    US states) are dissolved to a single union polygon. Idempotent: existing
    chips are skipped (cheap stat-based check).

    Returns stats dict: {'cut': int, 'skipped': int, 'raw_found': int}

    Raises FileNotFoundError if zero raw .nc files exist in the requested
    range under GLM_RAW_DIR/<goes_satellite>/. The error message names the
    date range and points the user at get_granules.py / download_from_urls.py.
    """
    if len(clip_gdf) > 1:
        clip_gdf = clip_gdf.dissolve()

    if verbose:
        area = aoi_area_in_km2(clip_gdf)
        print(f"area of [{out_name}] is approximately {round(area, 2)} km^2")

    goes_dir = GLM_RAW_DIR / goes_satellite
    out_dir = GLM_CLIP_DIR / out_name

    if verbose:
        print(f"goes_dir: {goes_dir}")

    path_list = find_files(goes_dir, start_dt_utc, end_dt_utc)
    raw_found = len(path_list)

    if raw_found == 0:
        raise FileNotFoundError(
            f"No raw GLM .nc files found in {goes_dir} for "
            f"[{start_dt_utc.isoformat()}, {end_dt_utc.isoformat()}). "
            f"Download raw granules first via get_granules.py + "
            f"download_from_urls.py for region '{out_name}', satellite {goes_satellite}."
        )

    if verbose:
        print(f"cutting chips for {raw_found} source files.")

    num_cut = 0
    num_skipped = 0
    product_abbr = GLM_VARIABLE_ABBR[TOE_IDX]

    for ridx, ncpath in enumerate(path_list):
        filestem = ncpath.stem
        partvec = ncpath.parent.parts   # ".../2023/12/20" → year, month, day
        year, month, day = partvec[-3:]

        tmp_out_dir = out_dir / f"{year}/{month}/{day}"
        tmp_out_dir.mkdir(parents=True, exist_ok=True)

        out_path = tmp_out_dir / f"{product_abbr}_{filestem}.tif"

        if not out_path.exists():
            # The GLM L3 NetCDF file stores variables in a fixed order matching
            # GLM_VARIABLES. Skip the extra netCDF4.Dataset open/close dance —
            # the variable name we want is known at compile time.
            var = GLM_VARIABLES[TOE_IDX]

            with rioxarray.open_rasterio(f"netcdf:{ncpath}:{var}") as netCDF_file:
                goesR_crs = netCDF_file.rio.crs
                reproj_clip_gdf = clip_gdf.to_crs(goesR_crs)
                file_clipped = netCDF_file.rio.clip(reproj_clip_gdf.geometry.apply(mapping))
                file_clipped.rio.to_raster(out_path)

            num_cut += 1
        else:
            num_skipped += 1

        if verbose:
            print(f"{ridx+1:>5}/{raw_found} {ncpath.name}", end="\r", flush=True)

        if max_items is not None and ridx + 1 >= max_items:
            if verbose:
                print("\nmax-items reached")
            break

    if verbose:
        print(" ")
        print(f"{num_cut} files clipped and written to {out_dir}")
        print(f"{num_skipped} files clipped previously.")

    return {'cut': num_cut, 'skipped': num_skipped, 'raw_found': raw_found}


def main(aoi=None,
        start_date=None,
        end_date=None,
        max_items=None,
        goes_satellite=None,
        utc=False):

    start_dt_utc, end_dt_utc, local_tz = parse_date_range(start_date, end_date, aoi=aoi, utc=utc)

    if end_dt_utc <= start_dt_utc:
        raise ValueError("start-date should be < end-date")
    print(f"Date range: {format_time_display(start_dt_utc, local_tz)} → {format_time_display(end_dt_utc, local_tz)}")

    aoi_gdf = load_geometry(aoi)
    if len(aoi_gdf) != 1:
        raise ValueError("This code only understands simple geometries")

    ensure_chips(
        out_name=aoi,
        clip_gdf=aoi_gdf,
        start_dt_utc=start_dt_utc,
        end_dt_utc=end_dt_utc,
        goes_satellite=goes_satellite,
        max_items=max_items,
    )


def parse_opt():
    parser = argparse.ArgumentParser()
    parser.add_argument('--aoi', type=str, default=None, required=True, choices=aoi_list(), help='name of AOI')
    parser.add_argument('--start-date', type=str, default='2023-08-01', required=True, help='start-date of search - needed to find correct csv')
    parser.add_argument('--end-date', type=str, help="end-date of search, if None, then use today's date - needed to find correct csv")
    parser.add_argument('--max-items', type=int, default=1, help="download first max-items from sorted CSV. Skips previously downloaded but counts them.")
    parser.add_argument('--goes-satellite', type=str, choices=['G16', 'G17', 'G18'], default="G18", help='which NOAA GOES satellite is this -> part of output_dir')
    parser.add_argument('--utc', action='store_true', help='interpret dates as UTC (default: AOI local time)')
    opt = parser.parse_args()
    return opt

if __name__ == "__main__":
    opt = parse_opt()
    main(**vars(opt))

#!/usr/bin/env python
"""
    sum_glm_chips.py - read previously cut .nc files (now geotifs), sum up all the files and output a sum_xxx.tif

    Guts of processing from:
    https://github.com/daniellelosos/GOES-R_NetCDF_to_GeoTIFF/blob/main/Clip%20with%20Shapefile.ipynb

"""
import argparse
import sys

import geopandas as gpd
import numpy as np
import rasterio

from scintilla.common.defines import GIS_DIR, GLM_CLIP_DIR
from scintilla.common.utils import (
    aoi_area_in_km2,
    aoi_list,
    clean_state_name,
    find_files,
    format_time_display,
    geometry_gdf_to_json,
    load_geometry,
    parse_date_range,
    validate_state_name,
)


def sum_geotiffs(file_paths, output_path):
    # List to hold the data of each GeoTIFF
    data_list = []
    # Metadata for the new GeoTIFF
    meta = None

    # Read each GeoTIFF
    for path in file_paths:
        with rasterio.open(path) as src:
            # If metadata is None, take it from the first file
            if meta is None:
                meta = src.meta.copy()
            # Append the data array to the list
            data_list.append(src.read(1))

    # Stack the arrays and sum along the new axis
    stacked_data = np.stack(data_list, axis=0)
    sum_data = np.sum(stacked_data, axis=0)
    uber_total = np.sum(stacked_data)
    print(f"sum of all {len(file_paths)} files: {uber_total}")

    # Update meta to reflect the number of layers is now 1
    meta.update(count=1)

    # Write the summed data to a new GeoTIFF file
    with rasterio.open(output_path, 'w', **meta) as dst:
        dst.write(sum_data, 1)




def main(aoi=None,
        state=None,
        start_date=None,
        end_date=None,
        mission=None,
        utc=False):

    start_dt_utc, end_dt_utc, local_tz = parse_date_range(start_date, end_date, aoi=aoi, utc=utc)

    if end_dt_utc <= start_dt_utc:
        raise ValueError("start-date should be < end-date")
    print(f"Date range: {format_time_display(start_dt_utc, local_tz)} → {format_time_display(end_dt_utc, local_tz)}")

    #-----------------------------------------------------------------------
    # only one of --aoi or --state will be non-Null
    if aoi:

        aoi_gdf = load_geometry(aoi)
        if len(aoi_gdf) != 1:
            raise ValueError("This code only understands simple geometries")
        geometry_gdf_to_json(aoi_gdf)   # this is just the {'type':'Polygon', 'coordinates': [[(), ()]]}

        area = aoi_area_in_km2(aoi_gdf)
        print(f"area of [{aoi}] AOI is approximately {round(area, 2)} km^2")

        clip_dir = GLM_CLIP_DIR / aoi
        print(f"goes_dir: {clip_dir}")

        out_dir = GLM_CLIP_DIR / aoi
        output_path = out_dir / f"{aoi}_clip_sum.tif"

    else:
        states_shape_path = GIS_DIR / "cb_2018_us_state_5m.zip"
        us_state_borders_gdf = gpd.read_file(states_shape_path)

        validate_state_name(us_state_borders_gdf, state)

        clean_state = clean_state_name(state)   # -> lower case " " -> "_"
        clip_dir = GLM_CLIP_DIR / clean_state
        print(f"goes_dir: {clip_dir}")

        out_dir = GLM_CLIP_DIR / clean_state
        output_path = out_dir / f"{clean_state}_clip_sum.tif"



    # this function walks goes_dir, finds all .nc files, then filters them by >= start_dt_utc, < end_dt_utc
    # returns a list of Path objects
    path_list = find_files(clip_dir, start_dt_utc, end_dt_utc, ext='tif')

    if len(path_list) == 0:
        print(f"No chips found matching date range {start_dt_utc} - {end_dt_utc}")
        return

    print(f"summing {len(path_list)} geotiffs")
    # Example usage


    sum_geotiffs(path_list, output_path)
    print(f"summed file written to {output_path}")



def parse_opt():
    parser = argparse.ArgumentParser()
    parser.add_argument('--aoi', type=str, default=None, choices=aoi_list(), help='name of AOI')
    parser.add_argument('--state', type=str, default=None, help='name of US State')

    parser.add_argument('--start-date', type=str, default='2023-08-01', required=True, help='start-date of search - needed to find correct csv')
    parser.add_argument('--end-date', type=str, help="end-date of search, if None, then use today's date - needed to find correct csv")
    parser.add_argument('--utc', action='store_true', help='interpret dates as UTC instead of AOI-local timezone')
    opt = parser.parse_args()

    # Check that exactly one of the options is provided
    if (opt.aoi is None) == (opt.state is None):
        parser.error('Exactly one of --aoi or --state must be specified.')
        sys.exit(1)

    return opt

if __name__ == "__main__":
    opt = parse_opt()
    main(**vars(opt))


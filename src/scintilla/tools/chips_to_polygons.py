#!/usr/bin/env python
"""
    chips_to_polygons.py - read geotiff files, for a given aoi, convert to individual geojson files

"""
import argparse
import sys
from itertools import groupby

import cv2
import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import xy
from shapely.geometry import MultiPoint, Polygon

from scintilla.common.defines import GIS_DIR, GLM_CLIP_DIR, GLM_POLYGON_DIR
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


def list_geo_tiff_bands(geo_tiff_path):
    """
    List the bands and their descriptions in a GeoTIFF file.

    Parameters:
    - geo_tiff_path: str, path to the GeoTIFF file

    Returns:
    - List of tuples containing (band_index, band_description)
    """
    with rasterio.open(geo_tiff_path) as src:
        band_descriptions = [(i + 1, src.descriptions[i] or f"Band {i + 1}") for i in range(src.count)]

    return band_descriptions


# extract_convex_hulls_from_geotiff: finds connected components
#   then extracts convex hull of each component, aggregating the TOE values
#   into mean, max, sum
def extract_convex_hulls_from_geotiff(geotiff_path, threshold_value=0):
    """
    Extracts convex hulls of connected components from a GeoTIFF image and returns them as a GeoDataFrame.

    Parameters:
    - geotiff_path: str, path to the GeoTIFF file

    Returns:
    - GeoDataFrame with each convex hull as a geometry
    """

    # bands = list_geo_tiff_bands(geotiff_path)
    # for band in bands:
    #     print(f"Band {band[0]}: {band[1]}")
    # pdb.set_trace()

    # Load the GeoTIFF file
    with rasterio.open(geotiff_path) as src:
        if src.count != 1:
            raise RuntimeError(f"Expected only one band here but got {src.count}")

        img = src.read(1)  # Assuming the components are in the first band
        src.descriptions[0]     # bands are 1-based, but descriptions are 0-based
        transform = src.transform
        crs = src.crs

        #print(f"min(image): {img.min()}, max(image): {img.max()}")

        # Threshold the image to make sure it is binary - input images are uint16
        _, binary = cv2.threshold(img, threshold_value, 255, cv2.THRESH_BINARY)

        # Ensure the result is uint8 if needed for further processing
        binary = binary.astype(np.uint8)

        # Find connected components - labels is the same shape as img, with label ids
        num_labels, labels = cv2.connectedComponents(binary)

    # Function to convert pixel coordinates to geographic coordinates
    def pixel_to_geo_coords(row, col):
        """Convert pixel coordinates to geographic coordinates using the transform."""
        x, y = xy(transform, row, col, offset='center')
        return x, y

    # Collect polygons from each component
    polygons = []
    mean_values = []
    max_values = []
    sum_values = []

    num_degen_shapes = 0

    for label in range(1, num_labels):  # Start from 1 to skip background

        # Isolate pixels of the current component
        component_mask = (labels == label)

        # Calculate the mean value of original image pixels within this component
        mean_value = img[component_mask].mean()
        max_value = img[component_mask].max()
        sum_value = img[component_mask].sum()


        # Find pixels of the current component
        y_indices, x_indices = np.where(labels == label)

        # Create a list of geographic coordinates
        coords = [pixel_to_geo_coords(y, x) for y, x in zip(y_indices, x_indices, strict=False)]

        # Generate a convex hull polygon from points
        if coords:
            poly = MultiPoint(coords).convex_hull
            if poly.geom_type == 'Polygon':
                mean_values.append(mean_value)
                max_values.append(max_value)
                sum_values.append(sum_value)
                polygons.append(poly)
            else:
                # there are degenerate cases of single points or lines
                num_degen_shapes += 1


    # Create a GeoDataFrame
    # TODO: This is wired for Total Optical Energy - could be better generalized
    gdf = gpd.GeoDataFrame({'geometry': polygons,
                            'mean_TOE': mean_values,
                            'max_TOE': max_values,
                            'sum_TOE': sum_values}, crs=crs)

    return gdf, num_degen_shapes


# create_pixel_polygons: treats each pixel in src images independently
def create_pixel_polygons(geotiff_path, threshold_value=0):
    with rasterio.open(geotiff_path) as src:
        img = src.read(1)
        transform = src.transform
        crs = src.crs

    polygons = []
    toe_values = []


    # Threshold the image to make sure it is binary - input images are uint16
    _, binary = cv2.threshold(img, threshold_value, 255, cv2.THRESH_BINARY)

    # Ensure the result is uint8 if needed for further processing
    binary = binary.astype(np.uint8)

    # Use np.where to find the indices of all pixels that are part of the foreground
    rows, cols = np.where(binary == 255)

    # Iterate over all pixels
    for row, col in zip(rows, cols, strict=False):
        # Apply the affine transform to each corner of the pixel
        top_left = transform * (col, row)
        top_right = transform * (col + 1, row)
        bottom_right = transform * (col + 1, row + 1)
        bottom_left = transform * (col, row + 1)

        # Create a polygon using these transformed coordinates
        poly = Polygon([top_left, top_right, bottom_right, bottom_left])
        polygons.append(poly)

        # save the toe value
        toe_values.append(img[row, col])


    gdf = gpd.GeoDataFrame({'geometry': polygons,
                            'toe': toe_values}, crs=crs)

    # don't think we can get any degenerte polygons (point, line) since this
    # is pixel-based
    num_degen_polys = 0

    return gdf, num_degen_polys

# extract_uniform_polygons_from_geotiff: creates polygons around each
# connected component with the same TOE value
def extract_uniform_polygons_from_geotiff(geotiff_path, threshold_value=0):

    with rasterio.open(geotiff_path) as src:
        img = src.read(1)  # Assume single band
        src_transform = src.transform
        crs = src.crs

    unique_values = np.unique(img)
    unique_values = unique_values[unique_values > threshold_value]

    if len(unique_values) == 0:
        return gpd.GeoDataFrame(), 0

    polygons = []
    toe_values = []
    num_degen_shapes = 0

    for value in unique_values:
        binary_image = (img == value).astype(np.uint8)

        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary_image, connectivity=8)
        for label_num in range(1, num_labels):
            component_mask = (labels == label_num).astype(np.uint8) * 255

            contours, hierarchy = cv2.findContours(component_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            for contour in contours:
                if len(contour) < 3:
                    num_degen_shapes += 1
                    continue

                # Convert pixel coordinates to geographic coordinates
                geo_coords = []
                for point in contour:
                    col, row = point[0]
                    x, y = xy(src_transform, row, col)
                    geo_coords.append((x, y))

                poly = Polygon(geo_coords)
                if poly.is_valid and poly.geom_type == 'Polygon':
                    polygons.append(poly)
                    toe_values.append(value)
                else:
                    num_degen_shapes += 1

    gdf = gpd.GeoDataFrame({'geometry': polygons,
                            'toe': toe_values}, crs=crs)

    return gdf, num_degen_shapes






def process_by_time_chunks(data_list, polygon_type, chunk_size, gpkg_path):
    """
    Process a list of dictionaries containing 'dt' and 'path' by chunks of time.

    Parameters:
    - data_list: list of dictionaries, each containing a datetime ('dt') and a path ('path')
    - chunk_size: str, one of ['all', 'week', 'day', 'hour', 'minute']
    """

    # Function to get the key for grouping
    def get_time_key(item):
        if chunk_size == 'all':
            return 'all'
        elif chunk_size == 'week':
            return (item['dt'].year, item['dt'].isocalendar().week)
        elif chunk_size == 'day':
            return (item['dt'].year, item['dt'].month, item['dt'].day)
        elif chunk_size == 'hour':
            return (item['dt'].year, item['dt'].month, item['dt'].day, item['dt'].hour)
        elif chunk_size == 'minute':
            return (item['dt'].year, item['dt'].month, item['dt'].day, item['dt'].hour, item['dt'].minute)

    # Group by the desired time chunk
    grouped_data = groupby(data_list, key=get_time_key)

    # Process each group
    num_valid_layers = 0
    num_empty_layers = 0

    for key, group in grouped_data:
        group_data = list(group)
        print(f"Processing group: {key} ({len(group_data)} items)")  # or any processing function call
        gdf = process_group(group_data, polygon_type)  # Assuming process_group is the function you have to process each chunk

        if isinstance(gdf, gpd.GeoDataFrame):
            lname = "-".join([str(k) for k in key])
            gdf.to_file(gpkg_path, layer=lname, driver="GPKG")
            num_valid_layers += 1
        else:
            num_empty_layers += 1

    print(f"\n{num_valid_layers} layers created.  ({num_empty_layers} empty layers skipped)")



def process_group(group, polygon_type):
    path_list = [pdict['path'] for pdict in group]
    gdf_list = []
    num_empties = 0

    group_non_polys = 0

    for _ridx, geotiff_path in enumerate(path_list):
        #print(f"geotiff_path: {geotiff_path}")

        if polygon_type == 'pixel':
            gdf, file_non_polys = create_pixel_polygons(geotiff_path)
        elif polygon_type == 'connected':
            gdf, file_non_polys = extract_convex_hulls_from_geotiff(geotiff_path)
        elif polygon_type == 'uniform':
            gdf, file_non_polys = extract_uniform_polygons_from_geotiff(geotiff_path)
        else:
            raise ValueError(
                f"Unknown polygon_type {polygon_type!r}. "
                f"Expected one of: 'pixel', 'connected', 'uniform'."
            )


        group_non_polys += file_non_polys

        if len(gdf) > 0:
            gdf_wgs84 = gdf.to_crs(epsg=4326)

            print(f"\t{str(geotiff_path.name):<80} num_polygons: {len(gdf)}", end="\r")

            gdf_list.append(gdf_wgs84)
        else:
            num_empties += 1


    if len(gdf_list) == 0:
        return None

    # Concatenate GeoDataFrames
    uber_gdf = gpd.GeoDataFrame(pd.concat(gdf_list, ignore_index=True))
    print(f"\n\t{len(uber_gdf)} frames with polygons, {num_empties} empty frames, {group_non_polys} non-polygons dropped")
    return uber_gdf


def main(aoi=None,
        state=None,
        start_date=None,
        end_date=None,
        chunk_size=None,
        polygon_type=None,
        utc=False):

    start_dt_utc, end_dt_utc, local_tz = parse_date_range(start_date, end_date, aoi=aoi, utc=utc)

    if end_dt_utc <= start_dt_utc:
        raise ValueError("start-date should be < end-date")
    print(f"Date range: {format_time_display(start_dt_utc, local_tz)} → {format_time_display(end_dt_utc, local_tz)}")

    #-----------------------------------------------------------------------

    if aoi:
        aoi_gdf = load_geometry(aoi)
        if len(aoi_gdf) != 1:
            raise ValueError("This code only understands simple geometries")
        geometry_gdf_to_json(aoi_gdf)   # this is just the {'type':'Polygon', 'coordinates': [[(), ()]]}

        area = aoi_area_in_km2(aoi_gdf)
        print(f"area of [{aoi}] AOI is approximately {round(area, 2)} km^2")


        geotiff_dir = GLM_CLIP_DIR / aoi
        print(f"geotiff_dir: {geotiff_dir}")

        suffix = ".gpkg" if chunk_size == 'all' else f"_{chunk_size}.gpkg"
        out_path = GLM_POLYGON_DIR / f"{aoi}/{aoi}_{polygon_type}_{start_dt_utc.strftime('%Y-%m-%d')}_{end_dt_utc.strftime('%Y-%m-%d')}{suffix}"
        out_path.parent.mkdir(exist_ok=True, parents=True)

    else:
        states_shape_path = GIS_DIR / "cb_2018_us_state_5m.zip"
        us_state_borders_gdf = gpd.read_file(states_shape_path)

        validate_state_name(us_state_borders_gdf, state)

        clean_state = clean_state_name(state)

        geotiff_dir = GLM_CLIP_DIR / clean_state
        print(f"geotiff_dir: {geotiff_dir}")

        suffix = ".gpkg" if chunk_size == 'all' else f"_{chunk_size}.gpkg"
        out_path = GLM_POLYGON_DIR / f"{clean_state}/{clean_state}_{polygon_type}_{start_dt_utc.strftime('%Y-%m-%d')}_{end_dt_utc.strftime('%Y-%m-%d')}{suffix}"
        out_path.parent.mkdir(exist_ok=True, parents=True)



    #states_shape_path = GIS_DIR / "cb_2018_us_state_5m.zip"
    #us_state_borders_gdf = gpd.read_file(states_shape_path)
    # If desired, select geometry subset by editing the field (ie.'NAME') and value (ie.'Florida')
    #az_border_gdf = us_state_borders_gdf[us_state_borders_gdf['NAME'] == 'Arizona']

    # this function walks goes_dir, finds all .nc files, then filters them by >= start_dt_utc, < end_dt_utc
    # returns a list of Path objects
    #path_list = find_files(geotiff_dir, start_dt_utc, end_dt_utc, ext="tif")

    path_dict_list = find_files(geotiff_dir, start_dt_utc, end_dt_utc, ext="tif", return_by='dict')

    if len(path_dict_list) == 0:
        print(f"Nothing matching date range in {geotiff_dir}")
        sys.exit(0)

    process_by_time_chunks(path_dict_list, polygon_type, chunk_size, out_path)

    print(f"done. geodatabase written to {out_path}")

    # # Concatenate GeoDataFrames
    # uber_gdf = gpd.GeoDataFrame(pd.concat(gdf_list, ignore_index=True))

    # # Set CRS from the first GeoDataFrame
    # uber_gdf.crs = gdf_list[0].crs


    # out_path = "uber_gdf.geojson"
    # uber_gdf.to_file(out_path, driver='GeoJSON')

    # print(" ")
    # print(f"{len(uber_gdf)} total polygons {out_dir}")
    # print(f"{num_empties} clips were empty.")


def parse_opt():
    parser = argparse.ArgumentParser()
    parser.add_argument('--aoi', type=str, default=None, choices=aoi_list(), help='name of AOI')
    parser.add_argument('--state', type=str, default=None, help='name of state')

    parser.add_argument('--start-date', type=str, default='2023-08-01', required=True, help='start-date of search - needed to find correct csv')
    parser.add_argument('--end-date', type=str, help="end-date of search, if None, then use today's date - needed to find correct csv")
    parser.add_argument('--chunk-size', type=str, choices=['all', 'week', 'day', 'hour', 'minute'], required=True, help="store output polygons with layers corresponding to these time increments")
    parser.add_argument('--polygon-type', type=str, choices=['connected', 'pixel', 'uniform'], default='pixel', help="type of conversion to do from raster to polygon")
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


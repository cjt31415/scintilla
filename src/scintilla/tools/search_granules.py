#!/usr/bin/env python
"""
    search_granules.py - given a short-name and version, date-range and AOI,
        find matching granules, then save the URLs and other metadata to csv file.

"""
import argparse
import sys

import earthaccess as ea
import pandas as pd

from scintilla.common.defines import (
    GRANULE_METADATA_DIR,
)
from scintilla.common.granule_utils import extract_begin_end_times, extract_download_url
from scintilla.common.utils import (
    aoi_area_in_km2,
    aoi_list,
    format_time_display,
    geometry_gdf_to_json,
    load_geometry,
    mission_data,
    parse_date_range,
    polygon_to_bbox,
)


def main(aoi=None,
        start_date=None,
        end_date=None,
        max_items=None,
        mission=None,
        utc=False):

    start_dt_utc, end_dt_utc, local_tz = parse_date_range(start_date, end_date, aoi=aoi, utc=utc)

    start_utc = start_dt_utc.strftime("%Y-%m-%d %H:%M")
    end_utc = end_dt_utc.strftime("%Y-%m-%d %H:%M")

    if end_dt_utc <= start_dt_utc:
        raise ValueError("start-date should be < end-date")
    print(f"Date range: {format_time_display(start_dt_utc, local_tz)} → {format_time_display(end_dt_utc, local_tz)}")

    #-----------------------------------------------------------------------

    aoi_gdf = load_geometry(aoi)
    if len(aoi_gdf) != 1:
        raise ValueError("This code only understands simple geometries")
    aoi_geom_json = geometry_gdf_to_json(aoi_gdf)   # this is just the {'type':'Polygon', 'coordinates': [[(), ()]]}

    area = aoi_area_in_km2(aoi_gdf)
    print(f"area of [{aoi}] AOI is approximately {round(area, 2)} km^2")


    mission_info = mission_data(mission)
    short_name = mission_info['short_name']
    provider_id = mission_info['provider_id']
    version = mission_info['version']
    print(f"short-name: {short_name}, provider_id: {provider_id}, version: {version}")

    bbox = polygon_to_bbox(aoi_geom_json)



    ea.login(strategy="netrc", persist=True)       # see ~/.netrc

    # bounding_box = Lower Left Long, Lat,  Upper Right Long, Lat
    Query = ea.granule_query().short_name(short_name) \
                                        .temporal(start_utc, end_utc) \
                                        .bounding_box(*bbox)

    # had trouble with version for some reason
    # .temporal(start_dt_utc.strftime("%Y-%m-%d"), end_dt_utc.strftime("%Y-%m-%d")) \
    # .version(version) \

    num_hits = Query.hits()

    num_gets = min(num_hits, max_items)
    print(f"Getting {num_gets} granules out of {num_hits} matching query")

    granules = Query.get(num_gets)

    if len(granules) == 0:
        print("Nothing matching query")
        sys.exit(1)


    data_dict = {'begin_dt':[], 'end_dt': [], 'url':[]}
    for granule in granules:
        url = extract_download_url(granule)
        begin_datetime, end_datetime = extract_begin_end_times(granule)
        data_dict['begin_dt'].append(begin_datetime)
        data_dict['end_dt'].append(end_datetime)
        data_dict['url'].append(url)


    df = pd.DataFrame(data_dict)

    out_dir = GRANULE_METADATA_DIR / aoi
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / f"{mission}_{aoi}_{start_dt_utc.strftime('%Y-%m-%d')}_{end_dt_utc.strftime('%Y-%m-%d')}.csv"
    df.to_csv(out_path, header=True, index=False)

    print(f"{len(df)} granule urls written to {out_path}")







def parse_opt():
    parser = argparse.ArgumentParser()
    parser.add_argument('--aoi', type=str, default=None, required=True, choices=aoi_list(), help='name of AOI')
    parser.add_argument('--start-date', type=str, default='2023-08-01', required=True, help='start-date of search')
    parser.add_argument('--end-date', type=str, help="end-date of search, if None, then use today's date")
    parser.add_argument('--max-items', type=int, default=1, help="total_count from stats less than this to do search")
    parser.add_argument('--mission', type=str, choices=['GEDI', 'GLM', 'ISSLIS'], required=True, help='which NASA Mission wanted')
    parser.add_argument('--utc', action='store_true', help='interpret dates as UTC instead of AOI-local timezone')
    opt = parser.parse_args()
    return opt

if __name__ == "__main__":
    opt = parse_opt()
    main(**vars(opt))


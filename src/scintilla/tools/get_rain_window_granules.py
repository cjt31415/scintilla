#!/usr/bin/env python
"""
    get_rain_window_granules.py - given an <aoi>_rain_window_<start-date>_<end-date>.csv file
        (from weather/download_isd_station_data.py)
        find matching granules, then save the URLs and other metadata to csv file.

"""

import argparse
from datetime import datetime

import earthaccess as ea
import pandas as pd
from dateutil.parser import parse

from scintilla.common.defines import GRANULE_METADATA_DIR, ISD_WEATHER_DIR
from scintilla.common.granule_utils import extract_begin_end_times, extract_download_url
from scintilla.common.utils import (
    aoi_area_in_km2,
    aoi_list,
    geometry_gdf_to_json,
    load_geometry,
    mission_data,
    polygon_to_bbox,
)


def main(aoi=None,
        start_date=None,
        end_date=None,
        max_items=None,
        mission=None):

    #-----------------------------------------------------------------------

    aoi_gdf = load_geometry(aoi)
    if len(aoi_gdf) != 1:
        raise ValueError("This code only understands simple geometries")
    aoi_geom_json = geometry_gdf_to_json(aoi_gdf)   # this is just the {'type':'Polygon', 'coordinates': [[(), ()]]}

    area = aoi_area_in_km2(aoi_gdf)
    print(f"area of [{aoi}] AOI is approximately {round(area, 2)} km^2")


    mission_dict = mission_data(mission)
    short_name = mission_dict['short_name']
    mission_dict['provider_id']
    mission_dict['version']
    mission_dict['daac']

    print(f"short-name: {mission_dict['short_name']}, daac: {mission_dict['daac']}, provider_id: {mission_dict['provider_id']}, version: {mission_dict['version']}")


    bbox = polygon_to_bbox(aoi_geom_json)

    #-----------------------------------------------------------------------

    start_dt = parse(start_date)
    end_dt = parse(end_date) if end_date else datetime.now()

    weather_dir = ISD_WEATHER_DIR / aoi
    rw_path = weather_dir / f"{aoi}_rainwin_{start_dt.strftime('%Y-%m-%d')}_{end_dt.strftime('%Y-%m-%d')}.csv"
    rw_df = pd.read_csv(rw_path, parse_dates=['start_date', 'end_date'])

    rw_df = rw_df.sort_values('total_rainfall', ascending=False).reset_index(drop=True)
    ea.login(strategy="netrc", persist=True)       # see ~/.netrc


    data_dict = {'begin_dt':[], 'end_dt': [], 'url':[]}

    for _ridx, row in rw_df.iterrows():
        start_utc = row['start_date']
        end_utc = row['end_date']

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

        for granule in granules:
            url = extract_download_url(granule)
            begin_datetime, end_datetime = extract_begin_end_times(granule)
            data_dict['begin_dt'].append(begin_datetime)
            data_dict['end_dt'].append(end_datetime)
            data_dict['url'].append(url)


    df = pd.DataFrame(data_dict)

    out_dir = GRANULE_METADATA_DIR / aoi
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / f"{mission}_{aoi}_{start_dt.strftime('%Y-%m-%d')}_{end_dt.strftime('%Y-%m-%d')}.csv"
    df.to_csv(out_path, header=True, index=False)

    print(f"{len(df)} granule urls written to {out_path}")







def parse_opt():
    parser = argparse.ArgumentParser()
    parser.add_argument('--aoi', type=str, default=None, required=True, choices=aoi_list(), help='name of AOI')
    #parser.add_argument('--rain-window-file', type=str, required=True, help='name of rain_window file')
    parser.add_argument('--start-date', type=str, required=True, help='start of datetime window')
    parser.add_argument('--end-date', type=str, required=True, help='end of datetime window')

    parser.add_argument('--max-items', type=int, default=1, help="total_count from stats less than this to do search")
    parser.add_argument('--mission', type=str, choices=['GEDI', 'GLM', 'ISSLIS'], required=True, help='which NASA Mission wanted')
    opt = parser.parse_args()
    return opt

if __name__ == "__main__":
    opt = parse_opt()
    main(**vars(opt))


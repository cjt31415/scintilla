#!/usr/bin/env python
"""
    find_isd_stations_within_aoi.py - read in the full ISD station metadata CSV,
        filter by --start-date --end-date and --aoi

        just prints out list

    usage: ./filter_isd_stations_by_region.py --help
"""


import argparse
import sys
from datetime import datetime

import pandas as pd
from dateutil.parser import parse
from shapely.geometry import Polygon

from scintilla.common.defines import METADATA_DIR
from scintilla.common.utils import aoi_area_in_km2, aoi_list, geometry_gdf_to_json, load_geometry
from scintilla.weather.weather_utils import is_station_within_polygon

# this can't be defined here because start_date, end_date, etc are not yet defined
#ISD_URL = f"https://www.ncei.noaa.gov/access/services/data/v1?dataset=global-hourly&startDate={start_date}&endDate={end_date}&stations={usaf}{wban}&format=json"

ISD_DATA_PATH = METADATA_DIR / "isd_station_metadata.csv"




def main(
        aoi=None,
        region=None,
        start_date=None,
        end_date=None):


    aoi_gdf = load_geometry(aoi)
    if len(aoi_gdf) != 1:
        raise ValueError("This code only understands simple geometries")
    aoi_geom_json = geometry_gdf_to_json(aoi_gdf)   # this is just the {'type':'Polygon', 'coordinates': [[(), ()]]}

    area = aoi_area_in_km2(aoi_gdf)
    print(f"area of [{aoi}] AOI is approximately {round(area, 2)} km^2")

    aoi_polygon = Polygon(aoi_geom_json['coordinates'][0])


    start_dt = parse(start_date)
    end_dt = parse(end_date) if end_date else datetime.now()

    isd_df = pd.read_csv(ISD_DATA_PATH)
    isd_df['BEGIN'] = pd.to_datetime(isd_df['BEGIN'], format='%Y%m%d')
    isd_df['END'] = pd.to_datetime(isd_df['END'], format='%Y%m%d')

    isd_df.dropna(subset=['BEGIN', 'END', 'LAT', 'LON'], inplace=True)

    # filter by start_dt and end_dt
    isd_df = isd_df[(isd_df['BEGIN'] < end_dt) & (isd_df['END'] >= start_dt)]

    isd_df['in_aoi'] = isd_df.apply(lambda row: is_station_within_polygon(row['LAT'], row['LON'], aoi_polygon), axis=1)

    aoi_stations_df = isd_df[isd_df['in_aoi']]

    if len(aoi_stations_df) == 0:
        print("No stations within AOI")
        sys.exit(1)

    print(f"{len(aoi_stations_df)} stations in {aoi}")

    aoi_stations_df = aoi_stations_df.sort_values('STATION NAME')

    for _ridx, row in aoi_stations_df.iterrows():
        print(row['STATION NAME'])


def parse_opt():
    parser = argparse.ArgumentParser()
    parser.add_argument('--aoi', type=str, default=None, choices=aoi_list(), help='name of AOI')
    parser.add_argument('--start-date', type=str, default="2020-10-01", help='start of datetime window')
    parser.add_argument('--end-date', type=str , help='end of datetime window')
    opt = parser.parse_args()
    return opt

if __name__ == "__main__":
    opt = parse_opt()
    main(**vars(opt))


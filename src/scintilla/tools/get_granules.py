#!/usr/bin/env python
"""
    get_granules.py - given <start-date> and <end-date>
        find matching granules, then save the URLs and other metadata to csv file.

"""
import argparse
import sys

import earthaccess as ea
import pandas as pd

from scintilla.common.defines import (
    GRANULE_METADATA_DIR,
)
from scintilla.common.granule_utils import (
    extract_begin_end_times,
    extract_download_url,
    extract_S3_download_url,
)
from scintilla.common.utils import (
    aoi_area_in_km2,
    aoi_list,
    format_time_display,
    load_geometry,
    mission_data,
    parse_date_range,
)


def main(aoi=None,
        start_date=None,
        end_date=None,
        max_items=None,
        mission=None,
        goes_satellite='G18',
        utc=False):

    #-----------------------------------------------------------------------

    start_dt_utc, end_dt_utc, local_tz = parse_date_range(start_date, end_date, aoi=aoi, utc=utc)
    print(f"Date range: {format_time_display(start_dt_utc, local_tz)} → {format_time_display(end_dt_utc, local_tz)}")

    #-----------------------------------------------------------------------

    aoi_gdf = load_geometry(aoi)
    if len(aoi_gdf) != 1:
        raise ValueError("This code only understands simple geometries")

    area = aoi_area_in_km2(aoi_gdf)
    print(f"area of [{aoi}] AOI is approximately {round(area, 2)} km^2")

    mission_dict = mission_data(mission)
    short_name = mission_dict['short_name']
    print(f"short-name: {mission_dict['short_name']}, daac: {mission_dict['daac']}, "
          f"provider_id: {mission_dict['provider_id']}, version: {mission_dict['version']}")

    #-----------------------------------------------------------------------

    #weather_dir = ISD_WEATHER_DIR / aoi
    #rw_path = weather_dir / f"{aoi}_rainwin_{start_dt.strftime('%Y-%m-%d')}_{end_dt.strftime('%Y-%m-%d')}.csv"
    #rw_df = pd.read_csv(rw_path, parse_dates=['start_date', 'end_date'])

    #rw_df = rw_df.sort_values('total_rainfall', ascending=False).reset_index(drop=True)
    #pdb.set_trace()


    ea.login(strategy="netrc", persist=True)       # see ~/.netrc


    data_dict = {'begin_dt':[], 'end_dt': [], 'url':[], 's3url':[]}



    # bounding_box = Lower Left Long, Lat,  Upper Right Long, Lat
    # Query = ea.granule_query().short_name(short_name) \
    #                                     .temporal(start_dt_utc, end_dt_utc) \
    #                                     .bounding_box(*bbox)
    Query = ea.granule_query().short_name(short_name) \
                                        .temporal(start_dt_utc, end_dt_utc)

    # had trouble with version for some reason
    # .temporal(start_dt_utc.strftime("%Y-%m-%d"), end_dt_utc.strftime("%Y-%m-%d")) \
    # .version(version) \

    num_hits = Query.hits()

    num_gets = min(num_hits, max_items)
    print(f"Getting {num_gets} granules out of {num_hits} matching query")

    granules = Query.get(num_gets)

    if len(granules) == 0:
        print("Nothing matching query")

    if mission == 'GLM':
        for granule in granules:
            url = extract_download_url(granule)
            if url is None:
                continue
            # filter the G16/G17/G18 overlaps to the requested satellite
            if goes_satellite not in url:
                continue
            s3url = extract_S3_download_url(granule)
            begin_datetime, end_datetime = extract_begin_end_times(granule)
            data_dict['begin_dt'].append(begin_datetime)
            data_dict['end_dt'].append(end_datetime)
            data_dict['url'].append(url)
            data_dict['s3url'].append(s3url)

    elif mission == 'ISSLIS':
        for granule in granules:
            url = extract_download_url(granule)
            if url is None:
                continue
            if not url.endswith('.nc'):
                continue
            s3url = extract_S3_download_url(granule)
            begin_datetime, end_datetime = extract_begin_end_times(granule)
            data_dict['begin_dt'].append(begin_datetime)
            data_dict['end_dt'].append(end_datetime)
            data_dict['url'].append(url)
            data_dict['s3url'].append(s3url)

    elif mission == 'GEDI':
        for granule in granules:
            url = extract_download_url(granule)
            if url is None:
                continue
            s3url = extract_S3_download_url(granule)
            begin_datetime, end_datetime = extract_begin_end_times(granule)
            data_dict['begin_dt'].append(begin_datetime)
            data_dict['end_dt'].append(end_datetime)
            data_dict['url'].append(url)
            data_dict['s3url'].append(s3url)

    else:
        print(f"Unrecognized mission: {mission}")
        sys.exit(-1)



    df = pd.DataFrame(data_dict)
    df['begin_dt'] = pd.to_datetime(df['begin_dt'])
    df['end_dt'] = pd.to_datetime(df['end_dt'])
    df = df.sort_values('begin_dt').reset_index(drop=True)

    out_dir = GRANULE_METADATA_DIR / aoi
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / f"{mission}_{aoi}_{start_dt_utc.strftime('%Y-%m-%d')}_{end_dt_utc.strftime('%Y-%m-%d')}.csv"
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
    parser.add_argument('--goes-satellite', type=str, choices=['G16', 'G17', 'G18'], default='G18',
                        help='which GOES satellite to filter for (GLM only)')
    parser.add_argument('--utc', action='store_true', help='interpret dates as UTC instead of AOI-local timezone')
    opt = parser.parse_args()
    return opt

if __name__ == "__main__":
    opt = parse_opt()
    main(**vars(opt))


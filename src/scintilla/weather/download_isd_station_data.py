#!/usr/bin/env python
"""
    download_isd_station_data.py - download actual weather data by station name, start and end dates

    usage: ./download_isd_station_data.py --help
"""


import argparse
import sys
from datetime import datetime

import pandas as pd
from dateutil.parser import parse

from scintilla.common.defines import ISD_WEATHER_DIR, METADATA_DIR
from scintilla.common.utils import aoi_list, load_geometry
from scintilla.weather.weather_utils import (
    celsius_to_fahrenheit,
    create_rain_windows,
    download_isd_data,
    parse_rainfall,
    parse_temp,
)

# this can't be defined here because start_date, end_date, etc are not yet defined
#ISD_URL = f"https://www.ncei.noaa.gov/access/services/data/v1?dataset=global-hourly&startDate={start_date}&endDate={end_date}&stations={usaf}{wban}&format=json"

ISD_DATA_PATH = METADATA_DIR / "isd_station_metadata.csv"




def main(
        aoi=None,
        station_name=None,
        start_date=None,
        end_date=None,
        rain_thresh=None,
        save_raw_csv=False):


    load_geometry(aoi)    # only using aoi for output location - this is just test

    start_dt = parse(start_date)
    end_dt = parse(end_date) if end_date else datetime.now()

    #----------------------------------------------------------------------------------------------------
    isd_df = pd.read_csv(ISD_DATA_PATH)

    station_df = isd_df[isd_df['STATION NAME'] == station_name]
    assert len(station_df) == 1, f"Did not find unique station for {station_name}"

    #----------------------------------------------------------------------------------------------------

    usaf = station_df.iloc[0]['USAF']
    wban = station_df.iloc[0]['WBAN']

    data_dict_list = download_isd_data(usaf, wban, start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"))

    data_df = pd.DataFrame(data_dict_list)

    print(f"{len(data_df)} rows in data_df")

    if len(data_df) == 0:
        print(f"No weather data for {station_name}")
        sys.exit(0)

    #----------------------------------------------------------------------------------------------------
    data_df['datetime'] = pd.to_datetime(data_df['DATE'])

    data_df = data_df.sort_values('datetime')

    data_df.set_index('datetime', inplace=True)

    data_df = data_df[data_df['REPORT_TYPE'] == 'FM-15']

    data_df['temp_C'] = data_df['TMP'].apply(lambda tmp: parse_temp(tmp))
    data_df['temp_F'] = data_df['temp_C'].apply(lambda tmp: celsius_to_fahrenheit(tmp))

    # Not all ISD stations report precipitation — if there's no AA1 column,
    # mark rainfall as -1.0 sentinel so downstream filters still work. Matches
    # the existing guard in bulk_isd_download.py.
    if 'AA1' not in data_df.columns:
        data_df['rainfall'] = -1.0
    else:
        data_df['rainfall'] = data_df['AA1'].apply(lambda rain: parse_rainfall(rain))

    #----------------------------------------------------------------------------------------------------

    if save_raw_csv:
        out_dir = ISD_WEATHER_DIR / aoi
        out_dir.mkdir(parents=True, exist_ok=True)

        out_path = out_dir / f"{aoi}_raw_{start_dt.strftime('%Y-%m-%d')}_{end_dt.strftime('%Y-%m-%d')}.csv"

        data_df.to_csv(out_path, index=True, header=True)
        print(f"{len(data_df)} rows of raw weather data saved to {out_path}")

    #--------------------------------------------------------------------------
    # calculate rain windows

    tmp_df = data_df[data_df['rainfall'] > rain_thresh]
    print(f"After threshold have {len(tmp_df)} rows")
    if len(tmp_df) == 0:
        print("No rain at this location during this period")
        sys.exit(0)


    # # Example usage
    # data = {
    #     'date': pd.date_range(start='2023-01-01', end='2023-01-10'),
    #     'rainfall': [0.0, 2.5, 3.7, 1.2, 0.0, 0.0, 1.8, 2.3, 0.0, 0.0]
    # }
    # df = pd.DataFrame(data).set_index('date')

    # Claude 3.0
    rain_windows_df = create_rain_windows(data_df, rain_thresh=rain_thresh)
    print(rain_windows_df)


    out_dir = ISD_WEATHER_DIR / aoi
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{aoi}_rain_windows_{start_dt.strftime('%Y-%m-%d')}_{end_dt.strftime('%Y-%m-%d')}.csv"
    rain_windows_df.to_csv(out_path, index=False, header=True)
    print(f"{len(rain_windows_df)} rows of rain windows written to {out_path}")




def parse_opt():
    parser = argparse.ArgumentParser()
    parser.add_argument('--aoi', type=str, default=None, required=True, choices=aoi_list(), help='AOI name - for output of station data')
    parser.add_argument('--station-name', type=str, default=None, required=True, help='ISD station name - not restricted to any AOI')
    parser.add_argument('--start-date', type=str, default="2020-10-01", help='start of datetime window')
    parser.add_argument('--end-date', type=str , help='end of datetime window')
    parser.add_argument('--rain-thresh', type=float, default=0.05, help='ignore daily rain if < rain-thresh')

    parser.add_argument('--save-raw-csv', action='store_true', help="output filtered list to csv")
    opt = parser.parse_args()
    return opt

if __name__ == "__main__":
    opt = parse_opt()
    main(**vars(opt))


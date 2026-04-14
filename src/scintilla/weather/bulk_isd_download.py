#!/usr/bin/env python
"""
    bulk_isd_download.py - use list of stations in data/metadata/southwest_isd_stations.csv
        download actual weather data by station name, start and end dates

    usage: ./bulk_isd_download.py --help

    See https://www.visualcrossing.com/resources/documentation/weather-data/how-we-process-integrated-surface-database-historical-weather-data/
    for some info on columns
"""



import argparse
from datetime import datetime, timedelta

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
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
SW_ISD_DATA_PATH = METADATA_DIR / "southwest_isd_stations.csv"




def process_one_station(aoi, station_df, short_name, start_dt, end_dt, rain_thresh=0.0, save_raw_csv=False, debug=False):
    usaf = station_df.iloc[0]['USAF']
    wban = station_df.iloc[0]['WBAN']

    data_dict_list = download_isd_data(usaf, wban, start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"))

    data_df = pd.DataFrame(data_dict_list)

    if len(data_df) == 0:
        print(f"{short_name}: No weather data downloaded.")
        return

    #----------------------------------------------------------------------------------------------------
    data_df['datetime'] = pd.to_datetime(data_df['DATE'])

    data_df = data_df.sort_values('datetime')

    data_df.set_index('datetime', inplace=True)

    # FM-12 (SYNOP): These are standard surface weather observations from fixed land stations, reporting hourly data on weather conditions.
    # FM-15 (METAR): Meteorological Aerodrome Reports (METAR) are used primarily for aviation, providing detailed information about the weather at airport stations. They are typically issued every hour.
    data_df = data_df[(data_df['REPORT_TYPE'] == 'FM-12') | (data_df['REPORT_TYPE'] == 'FM-15')]

    if len(data_df) == 0:
        print(f"{short_name}: no report types == 'FM-12' or 'FM-15'")
        return


    data_df['temp_C'] = data_df['TMP'].apply(lambda tmp: parse_temp(tmp))
    data_df['temp_F'] = data_df['temp_C'].apply(lambda tmp: celsius_to_fahrenheit(tmp))

    if 'AA1' not in data_df.columns:
        data_df['rainfall'] = -1.0
    else:
        data_df['rainfall'] = data_df['AA1'].apply(lambda rain: parse_rainfall(rain))

    #----------------------------------------------------------------------------------------------------

    if save_raw_csv:
        out_dir = ISD_WEATHER_DIR / aoi
        out_dir.mkdir(parents=True, exist_ok=True)

        out_path = out_dir / f"{short_name}_raw_{start_dt.strftime('%Y-%m-%d')}_{end_dt.strftime('%Y-%m-%d')}.csv"

        data_df.to_csv(out_path, index=True, header=True)
        print(f"{short_name}: {len(data_df)} rows of raw weather data saved to {out_path}")

    #--------------------------------------------------------------------------
    # calculate rain windows

    tmp_df = data_df[data_df['rainfall'] > rain_thresh]
    if len(tmp_df) == 0:
        print(f"{short_name}: No rain at this location during this period")
        return


    # # Example usage
    # data = {
    #     'date': pd.date_range(start='2023-01-01', end='2023-01-10'),
    #     'rainfall': [0.0, 2.5, 3.7, 1.2, 0.0, 0.0, 1.8, 2.3, 0.0, 0.0]
    # }
    # df = pd.DataFrame(data).set_index('date')

    # Claude 3.0
    rain_windows_df = create_rain_windows(data_df, rain_thresh=rain_thresh)
    # print(rain_windows_df)


    out_dir = ISD_WEATHER_DIR / aoi
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{short_name}_rainwin_{start_dt.strftime('%Y-%m-%d')}_{end_dt.strftime('%Y-%m-%d')}.csv"
    rain_windows_df.to_csv(out_path, index=False, header=True)
    print(f"{short_name}: {len(rain_windows_df)} rows of rain windows written to {out_path}")


def find_matching_station(isd_station_metadata_df, station_name, start_dt, end_dt, use_datetime=False):

    # sometimes the master table is lagging behind in terms of the END date
    if use_datetime:
        station_df = isd_station_metadata_df[(isd_station_metadata_df['STATION NAME'] == station_name) & \
                                        (isd_station_metadata_df['BEGIN'] <= start_dt) & \
                                        (isd_station_metadata_df['END'] >= end_dt)]
    else:
        station_df = isd_station_metadata_df[isd_station_metadata_df['STATION NAME'] == station_name]

    return station_df


def merge_rainfall_dataframes(data_list):
    """
    Merges a list of dictionaries containing dataframes with rainfall data and overlapping time intervals.

    Parameters:
        data_list (list): A list of dictionaries, each containing a 'name' and 'df' key.
                          'df' is a pandas DataFrame with columns 'start_date', 'end_date', and 'total_rainfall'.

    Returns:
        pd.DataFrame: A DataFrame with merged intervals and summed rainfall totals.
    """
    # Extract dataframes from the list of dictionaries
    dfs = [item['df'] for item in data_list]

    df_combined = pd.concat(dfs)

    # Step 2: Sort by 'start_date'
    df_combined.sort_values(by='start_date', inplace=True)

    # Step 3: Merge overlapping intervals
    merged_intervals = []
    current_start, current_end, current_rain = None, None, 0

    for _index, row in df_combined.iterrows():
        if current_start is None:
            # Initialize the first row
            current_start, current_end, current_rain = row['start_date'], row['end_date'], row['total_rainfall']
        else:
            if row['start_date'] <= current_end:
                # There is an overlap
                current_end = max(current_end, row['end_date'])
                current_rain += row['total_rainfall']
            else:
                # No overlap
                merged_intervals.append([current_start, current_end, current_rain])
                current_start, current_end, current_rain = row['start_date'], row['end_date'], row['total_rainfall']

    # Append the last interval
    merged_intervals.append([current_start, current_end, current_rain])

    # Convert list to DataFrame
    df_final = pd.DataFrame(merged_intervals, columns=['start_date', 'end_date', 'total_rainfall'])

    return df_final





def display_rainfall_windows(data_list):
    """
    Displays a horizontal bar plot of rainfall windows for each dataset with dynamic x-axis formatting.

    Parameters:
        data_list (list): A list of dictionaries, each containing a 'name' and 'df' key.
                          'df' is a pandas DataFrame with columns 'start_date', 'end_date', and 'total_rainfall'.
    """
    # Prepare the plot
    fig, ax = plt.subplots(figsize=(14, 12))  # Dynamic figure size based on number of datasets

    # Calculate the total timespan across all datasets
    min_date = pd.to_datetime('2099-12-31')
    max_date = pd.to_datetime('1900-01-01')
    for item in data_list:
        df = item['df']
        min_date = min(min_date, df['start_date'].min())
        max_date = max(max_date, df['end_date'].max())
    delta = max_date - min_date

    # Dynamic date formatting on the x-axis based on data range
    if delta <= timedelta(days=2):
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=6))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d %H:%M'))
    elif delta <= timedelta(days=31):
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    else:
        ax.xaxis.set_major_locator(mdates.MonthLocator())
        ax.xaxis.set_minor_locator(mdates.WeekdayLocator(byweekday=(0)))  # Each Monday as a minor tick
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))

    # Create horizontal bars
    for _index, item in enumerate(data_list):
        df = item['df']
        df['total_rainfall'] = df['total_rainfall'].astype(float)
        for _, row in df.iterrows():
            start_date = mdates.date2num(row['start_date'])
            end_date = mdates.date2num(row['end_date'])
            ax.barh(item['name'], end_date - start_date, left=start_date, height=0.2, color='blue', align='center')

    # Set labels and title
    ax.set_xlabel('Date')
    ax.set_ylabel('Dataset')
    ax.set_title('Rainfall Windows by Dataset')
    ax.set_ylim(-0.5, len(data_list) - 0.5)
    ax.grid(True)

    # Rotate date labels for better readability
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", rotation_mode="anchor")

    # Adjust layout to prevent clipping of tick-labels
    plt.tight_layout()

    # Show the plot
    plt.show()

# Example usage: assuming `data_list` is your list of dictionaries containing 'name' and 'df'
# display_rainfall_windows(data_list)


def plot_rainfall(df):
    """
    Plots total rainfall against the midpoint of the rain window, with dynamic x-axis formatting
    based on the data's timespan.

    Parameters:
        df (pd.DataFrame): A DataFrame with 'start_date', 'end_date', and 'total_rainfall' columns.
    """
    # Calculate the midpoint of each rain window
    df['midpoint'] = df['start_date'] + (df['end_date'] - df['start_date']) / 2

    # Determine the total timespan of the data
    min_date = df['midpoint'].min()
    max_date = df['midpoint'].max()
    delta = max_date - min_date

    # Create the plot
    fig, ax = plt.subplots(figsize=(14, 6))
    ax.scatter(df['midpoint'], df['total_rainfall'], color='blue')

    # Dynamic date formatting on the x-axis based on data range
    if delta <= timedelta(days=4):
        # Hourly labels if the data is shorter than a few days
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=6))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d %H:%M'))
    elif delta <= timedelta(days=31):
        # Daily labels if the data is under a month
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    else:
        # Monthly labels, with minor ticks on weeks when the data is longer than a month
        ax.xaxis.set_major_locator(mdates.MonthLocator())
        ax.xaxis.set_minor_locator(mdates.WeekdayLocator(byweekday=(0)))  # Each Monday as a minor tick
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))

    plt.xticks(rotation=45)

    # Labels and title
    ax.set_xlabel('Date')
    ax.set_ylabel('Total Rainfall (inches)')
    ax.set_title('Total Rainfall vs. Date')

    # Show grid
    ax.grid(True)

    # Show the plot
    plt.tight_layout()
    plt.show()



def sum_total_rainfall(df):
    """
    Calculates the total number of unique days with rainfall.

    Parameters:
        df (pd.DataFrame): A DataFrame with 'start_date' and 'end_date' columns.

    Returns:
        int: Total number of unique days with rainfall.
    """
    # Extract just the date part from 'start_date' and 'end_date'
    start_dates = df['start_date'].dt.date
    end_dates = df['end_date'].dt.date

    # Combine the start and end dates into a single Series and find unique dates
    all_dates = pd.concat([start_dates, end_dates]).unique()

    # Count the number of unique days
    unique_days_count = len(set(all_dates))

    return unique_days_count


def main(
        aoi=None,
        start_date=None,
        end_date=None,
        rain_thresh=None,
        save_raw_csv=False,
        redo=False):


    load_geometry(aoi)    # only using aoi for output location - this is just test

    start_dt = parse(start_date)
    end_dt = parse(end_date) if end_date else datetime.now()

    #----------------------------------------------------------------------------------------------------
    isd_station_metadata_df = pd.read_csv(ISD_DATA_PATH, parse_dates=['BEGIN', 'END'])

    # these are the stations I'm interested in
    station_path = METADATA_DIR / f"{aoi}_isd_stations.csv"
    assert station_path.exists(), f"Did not find aoi-based station data: {station_path}"

    stations_df = pd.read_csv(station_path)
    stations_df = stations_df.sort_values('name').reset_index(drop=True)

    out_dir = ISD_WEATHER_DIR / aoi
    out_dir.mkdir(parents=True, exist_ok=True)

    for _ridx, row in stations_df.iterrows():
        short_name = row['name']
        station_name = row['isd_name']
        print(f"{short_name} ({station_name})")

        # do not used start or end dates if working in near-current time
        station_df = find_matching_station(isd_station_metadata_df, station_name, start_dt, end_dt, use_datetime=False)
        if len(station_df) != 1:

            #station_df = isd_station_metadata_df[isd_station_metadata_df['STATION NAME'] == station_name]
            #if len(station_df) != 1:
            print(f"Did not find unique station for {station_name}")

        do_download = True
        if not redo:

            out_path = out_dir / f"{short_name}_raw_{start_dt.strftime('%Y-%m-%d')}_{end_dt.strftime('%Y-%m-%d')}.csv"
            if out_path.exists():
                do_download = False


        if do_download:
            process_one_station(aoi, station_df, short_name, start_dt, end_dt, rain_thresh=rain_thresh, save_raw_csv=save_raw_csv)
        else:
            print(f"{short_name}: already downloaded.")

    #----------------------------------------------------------------------------------------------------
    # go back through, read the rain window dataframes then merge them

    rain_win_df_list = []

    for _ridx, row in stations_df.iterrows():
        short_name = row['name']
        station_name = row['isd_name']

        rw_path = out_dir / f"{short_name}_rainwin_{start_dt.strftime('%Y-%m-%d')}_{end_dt.strftime('%Y-%m-%d')}.csv"
        if rw_path.exists():
            df = pd.read_csv(rw_path, parse_dates=['start_date', 'end_date'])
            rain_win_df_list.append({'name':short_name, 'df':df})


    # display
    # sort the list by station name
    rain_win_df_list = sorted(rain_win_df_list, key=lambda sdict: sdict['name'], reverse=True)
    display_rainfall_windows(rain_win_df_list)

    final_df = merge_rainfall_dataframes(rain_win_df_list)
    plot_rainfall(final_df)

    # sum up the total number of days with some rain
    total_days = sum_total_rainfall(final_df)
    print(f"Total rainfall days during {start_dt}-{end_dt}: {total_days}")



def parse_opt():
    parser = argparse.ArgumentParser()
    parser.add_argument('--aoi', type=str, default=None, required=True, choices=aoi_list(), help='AOI name - for output of station data')
    parser.add_argument('--start-date', type=str, default="2020-10-01", help='start of datetime window')
    parser.add_argument('--end-date', type=str , help='end of datetime window')
    parser.add_argument('--rain-thresh', type=float, default=0.05, help='ignore daily rain if < rain-thresh')

    parser.add_argument('--save-raw-csv', action='store_true', help="output filtered list to csv")
    parser.add_argument('--redo', action='store_true', help="re-download all data")
    opt = parser.parse_args()
    return opt

if __name__ == "__main__":
    opt = parse_opt()
    main(**vars(opt))


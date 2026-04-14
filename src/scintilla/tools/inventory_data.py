#!/usr/bin/env python
"""
    inventory_data.py - walk DATA_DIR/<mission> and inventory what has been downloaded

"""

import argparse
import calendar
from datetime import datetime

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import ListedColormap

from scintilla.common.defines import DATA_DIR, GLM_RAW_DIR, ISSLIS_RAW_DIR

AOIS_EXCLUDED = ['.DS_Store', 'ndvi_test', 'ndvi_test_4bands', 'ndvi_test_8b_SR', 'test']
JUNK_FILES = ['.DS_Store']


def buckets_to_count_dict(bucket_list):

    date_cnt_dict = {}
    total_count = 0

    for bdict in bucket_list:
        # dates look like: '2023-08-01T00:00:00.000000Z'
        date_str = bdict['start_time'][:10]
        if date_str in date_cnt_dict:
            raise RuntimeError("Didn\'t expect duplicate dates")
        date_cnt_dict[date_str] = bdict['count']
        total_count += bdict['count']

    return date_cnt_dict, total_count


def get_min_max_dates(aoi_dates):
    all_dates = [date for dates in aoi_dates.values() for date in dates]
    min_date = min(all_dates)
    max_date = max(all_dates)
    return min_date, max_date


def plot_aoi_dates(aoi_dates, min_date, max_date):
    plt.figure(figsize=(14, 6))

    # Configure the X-axis to show dates by month
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    plt.gca().xaxis.set_major_locator(mdates.MonthLocator())
    plt.gcf().autofmt_xdate()

    # Set the range for the x-axis
    plt.xlim(min_date, max_date)

    # Plot circles for each AOI and date
    for i, (aoi, dates) in enumerate(aoi_dates.items()):
        plt.scatter(dates, [i] * len(dates), label=aoi)

    # Set yticks and yticklabels
    plt.yticks(range(len(aoi_dates)), list(aoi_dates.keys()))

    plt.xlabel('Dates')
    plt.ylabel('AOIs')
    plt.legend(loc='upper left', bbox_to_anchor=(1, 1))

    plt.title('AOI Scene Dates')
    plt.tight_layout(rect=[0, 0, 0.85, 1])  # Adjust the right boundary of the plot to make space for the legend

    plt.show()


def inventory_scenes():
    dtype_path = DATA_DIR / 'scenes'

    aoi_scene_dict = {}

    for meta_data in dtype_path.rglob("*_metadata.json"):
        aoi = meta_data.parent.parts[-1]

        if aoi not in AOIS_EXCLUDED:
            #print(f"{meta_data} -> {meta_data.parent.parts[-1]}")
            scene_parts = meta_data.stem.split('_')
            scene_id = '_'.join(scene_parts[:2])
            scn_dt = datetime.strptime(scene_id, "%Y%m%d_%H%M%S")
            #print(f"{scene_id} => {scn_dt}")
            if aoi in aoi_scene_dict:
                aoi_scene_dict[aoi].append(scn_dt)
            else:
                aoi_scene_dict[aoi] = [scn_dt]

    for k, v in aoi_scene_dict.items():
        aoi_scene_dict[k] = sorted(v)

    min_date, max_date = get_min_max_dates(aoi_scene_dict)
    plot_aoi_dates(aoi_scene_dict, min_date, max_date)


def calculate_offset(start_date, target_date):
    """
    Calculate the offset from the start date to the target date.

    Parameters:
    - start_date: A string representing the start date in 'YYYY-MM-DD' format.
    - target_date: A string representing the target date in 'YYYY-MM-DD' format.

    Returns:
    - offset: An integer representing the offset in days from the start date.
    """
    start_date = pd.to_datetime(start_date)
    target_date = pd.to_datetime(target_date)
    offset = (target_date - start_date).days
    return offset


def plot_GLM(data, start_dt, sat_name):

    # Convert this flat array into a 12x31 matrix
    calendar_view = np.full((12, 31), np.nan)  # Fill with NaNs which will be masked

    for i, count in enumerate(data):
        date = start_dt + pd.DateOffset(days=i)
        calendar_view[date.month - 1, date.day - 1] = count

    # Mask the NaN values so they aren't considered in the plot
    masked_calendar_view = np.ma.masked_invalid(calendar_view)

    # Plotting
    fig, ax = plt.subplots(figsize=(10, 6))

    # Define a 5-level quantized 'virdis' colormap
    #jet = cm.get_cmap('Blues', 256)  # get the jet color map
    #newcolors = jet(np.linspace(0, 1, 5))  # pick 5 evenly spaced colors from jet colormap
    #cmap = ListedColormap(newcolors)  # create a new ListedColormap

    # Define a new colormap with oranges replacing the pinks
    cmap = ListedColormap(['#ffffff', '#ffe6cc', '#ffcc99', '#ff9933', '#cc6600'])  # From white to deep orange


    #cmap = ListedColormap(['#ffffff', '#ffcccb', '#fca3cc', '#fc5185'])  # Custom colormap
    # Define a 5-level blue/green/yellow color ramp
    #cmap = ListedColormap(['#004c6d', '#347474', '#599a6f', '#9bc77e', '#f6ed6c'])  # Dark blue to yellow

    cax = ax.imshow(masked_calendar_view, cmap=cmap, aspect='auto')

    # Set ticks
    ax.set_xticks(range(31))
    ax.set_xticklabels(range(1, 32))  # Days from 1 to 31
    ax.set_yticks(range(12))
    ax.set_yticklabels(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'])

    # Add color bar
    plt.colorbar(cax, ax=ax, orientation='vertical')
    plt.title(f'Daily File Counts ({start_dt.year}) for {sat_name}')
    plt.xlabel('Day of the Month')
    plt.ylabel('Month')
    plt.grid(False)  # Disable grid or set it to True based on your preference
    plt.show()


def inventory_GLM(year, debug=False):
    start_dt = datetime.strptime(f"{year}-01-01", "%Y-%m-%d")
    glm_path = GLM_RAW_DIR

    #date_range = pd.date_range(start=start_date, end=end_date, freq='D')
    days_in_year = get_number_of_days_in_year(year)

    # top-level of GLM is the platform (e.g. G16, G17, G18)
    sat_dirs = glm_path.glob("*")
    sat_names = [d.name for d in sat_dirs if d.is_dir()]

    for sat_name in sat_names:
        print(f"processing GLM satellite: {sat_name}")
        # count_data is your flat array with the file count for each day of the year.
        count_data = np.zeros(days_in_year)

        sat_path = glm_path / f"{sat_name}/{year}"
        for _pidx, nc_path in enumerate(sat_path.rglob("**/*.nc")):
            # parts of ".../G18/2023/9/23/filename.nc" → file_year, file_month, file_day
            file_year, file_month, file_day = (int(x) for x in nc_path.parent.parts[-3:])
            file_date = f"{file_year}-{file_month:02}-{file_day:02}"
            offset = calculate_offset(start_dt, file_date)
            count_data[offset] += 1

            # if pidx > 1000:
            #     break

        plot_GLM(count_data, start_dt, sat_name)


def inventory_ISSLIS(year, debug=False):
    start_dt = datetime.strptime(f"{year}-01-01", "%Y-%m-%d")
    iss_path = ISSLIS_RAW_DIR

    days_in_year = get_number_of_days_in_year(year)
    count_data = np.zeros(days_in_year)

    sat_path = iss_path / f"{year}"
    for _pidx, nc_path in enumerate(sat_path.rglob("**/*.nc")):
        # parts of ".../isslis/2023/9/23/filename.nc" → file_year, file_month, file_day
        file_year, file_month, file_day = (int(x) for x in nc_path.parent.parts[-3:])
        file_date = f"{file_year}-{file_month:02}-{file_day:02}"
        offset = calculate_offset(start_dt, file_date)
        count_data[offset] += 1

    plot_GLM(count_data, start_dt, "ISSLIS")


def parse_dir_date(directory_name):
    try:
        # Try the first format
        parsed_date = datetime.strptime(directory_name, "%Y-%m")
        print(f"Processed with format '%Y_%m': {parsed_date}")
        return parsed_date
    except ValueError:
        try:
            # Try the second format
            parsed_date = datetime.strptime(directory_name, "%Y-%m-%d")
            print(f"Processed with format '%Y_%m_%d': {parsed_date}")
            return parsed_date
        except ValueError:
            # If both fail, ignore or handle the directory
            print(f"Directory '{directory_name}' does not match expected formats.")
            return None


def get_number_of_days_in_year(year):
    # Returns 366 if it's a leap year, otherwise 365
    return 366 if calendar.isleap(year) else 365


def main(year=None,
        mission=None):

    if mission == 'GLM':
        inventory_GLM(year)
    elif mission == 'ISSLIS':
        inventory_ISSLIS(year)
    else:
        print(f"inventory {mission} - not implemented yet")





def parse_opt():
    parser = argparse.ArgumentParser()
    parser.add_argument('--year', type=int, required=True, help='year to inventory')

    parser.add_argument('--mission', type=str, choices=['GEDI', 'GLM', 'ISSLIS'], required=True, help='which NASA Mission wanted')
    opt = parser.parse_args()
    return opt

if __name__ == "__main__":
    opt = parse_opt()
    main(**vars(opt))


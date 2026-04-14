#!/usr/bin/env python
"""
    download_from_urls.py - read a csv of DAAC HTTPS urls and download each.

    The S3 path that used to live in here was extracted to
    archive/tools/download_from_S3.py — it was never working end-to-end.
"""
import argparse
import shutil
import sys
import time
from urllib.parse import urlparse

import earthaccess
import pandas as pd

from scintilla.common.defines import GEDI_RAW_DIR, GLM_RAW_DIR, GRANULE_METADATA_DIR, ISSLIS_RAW_DIR
from scintilla.common.utils import (
    aoi_area_in_km2,
    aoi_list,
    format_time_display,
    load_geometry,
    mission_data,
    parse_date_range,
)


def download_file_with_retry(fs, url, out_path, max_retries=5, delay_seconds=10):
    """Download `url` to `out_path` via fsspec, retrying on transient errors.

    Streams in 4 MB chunks via shutil.copyfileobj instead of remote_file.read(),
    so a 50+ MB GLM raw .nc file no longer round-trips through RAM as a single
    bytes blob.
    """
    attempts = 0
    while attempts < max_retries:
        try:
            with fs.open(url, 'rb') as remote_file, open(out_path, "wb") as local_file:
                shutil.copyfileobj(remote_file, local_file, length=4 * 1024 * 1024)
            return
        except Exception as e:
            print(f"Attempt {attempts + 1} failed: {e}")
            attempts += 1
            time.sleep(delay_seconds)
            if attempts >= max_retries:
                print("Failed to download file after several attempts")
                raise


def main(aoi=None,
        start_date=None,
        end_date=None,
        max_items=None,
        goes_satellite=None,
        mission=None,
        utc=False):

    start_dt_utc, end_dt_utc, local_tz = parse_date_range(start_date, end_date, aoi=aoi, utc=utc)

    if end_dt_utc <= start_dt_utc:
        raise ValueError("start-date should be < end-date")
    print(f"Date range: {format_time_display(start_dt_utc, local_tz)} → {format_time_display(end_dt_utc, local_tz)}")

    aoi_gdf = load_geometry(aoi)
    if len(aoi_gdf) != 1:
        raise ValueError("This code only understands simple geometries")

    area = aoi_area_in_km2(aoi_gdf)
    print(f"area of [{aoi}] AOI is approximately {round(area, 2)} km^2")

    meta_dir = GRANULE_METADATA_DIR / aoi
    if not meta_dir.exists():
        raise FileNotFoundError(f"Could not find metadata dir: {meta_dir}")

    csv_path = meta_dir / f"{mission}_{aoi}_{start_date}_{end_date}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"Could not find metadata file: {csv_path}")

    meta_df = pd.read_csv(csv_path, parse_dates=['begin_dt', 'end_dt'])
    print(f"{len(meta_df)} files to download.")
    if len(meta_df) > max_items:
        print(f"max-items is {max_items} - increase to download more - okay to repeat")

    if mission == 'GLM':
        out_dir = GLM_RAW_DIR / goes_satellite
    elif mission == 'ISSLIS':
        out_dir = ISSLIS_RAW_DIR
    elif mission == 'GEDI':
        out_dir = GEDI_RAW_DIR
    else:
        print(f"Mission {mission!r} not implemented")
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"out_dir: {out_dir}")

    earthaccess.login(strategy="netrc", persist=True)       # see ~/.netrc

    mission_dict = mission_data(mission)
    print(f"short-name: {mission_dict['short_name']}, daac: {mission_dict['daac']}, "
          f"provider_id: {mission_dict['provider_id']}, version: {mission_dict['version']}")

    fs = earthaccess.get_fsspec_https_session()

    num_downloaded = 0
    already_downloaded = 0

    for ridx, row in meta_df.iterrows():
        start_dt = row['begin_dt']
        tmp_out_dir = out_dir / f"{start_dt.year}/{start_dt.month}/{start_dt.day}"
        tmp_out_dir.mkdir(parents=True, exist_ok=True)

        url = row['url']
        if pd.isna(url) or not url:
            print(f"row {ridx}: missing url, skipping")
            continue
        parsed_url = urlparse(url)
        filename = parsed_url.path.split('/')[-1]
        out_path = tmp_out_dir / filename

        if not out_path.exists():
            download_file_with_retry(fs, url, out_path)
            num_downloaded += 1
        else:
            already_downloaded += 1

        print(f"{ridx+1:>4}/{len(meta_df):<5} {filename}", end="\r", flush=True)

        if ridx+1 >= max_items:
            print("\nmax-items reached")
            break

    print(" ")
    print(f"{num_downloaded} files downloaded to {out_dir}")
    print(f"{already_downloaded} files downloaded previously.")


def parse_opt():
    parser = argparse.ArgumentParser()
    parser.add_argument('--aoi', type=str, default=None, required=True, choices=aoi_list(), help='name of AOI')
    parser.add_argument('--start-date', type=str, default='2023-08-01', required=True, help='start-date of search - needed to find correct csv')
    parser.add_argument('--end-date', type=str, help="end-date of search, if None, then use today's date - needed to find correct csv")
    parser.add_argument('--max-items', type=int, default=1, help="download first max-items from sorted CSV. Skips previously downloaded but counts them.")
    parser.add_argument('--goes-satellite', type=str, choices=['G16', 'G17', 'G18'], default="G18", help='which NOAA GOES satellite is this -> part of output_dir')
    parser.add_argument('--mission', type=str, choices=['GEDI', 'GLM', 'ISSLIS'], required=True, help='which NASA Mission wanted - needed to find correct csv')
    parser.add_argument('--utc', action='store_true', help='interpret dates as UTC instead of AOI-local timezone')
    return parser.parse_args()


if __name__ == "__main__":
    opt = parse_opt()
    main(**vars(opt))

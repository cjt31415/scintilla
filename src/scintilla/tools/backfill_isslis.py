#!/usr/bin/env python
"""
    backfill_isslis.py - download missing ISS LIS .nc files for a date range.

    Walks the date range month-by-month so a failure in one month doesn't
    lose progress in others. Files are filed into ISSLIS_RAW_DIR/<Y>/<M>/<D>/
    to match the existing layout. Skips files already on disk (idempotent —
    safe to re-run).

    Default range covers the pre-2020 gap (2017-03-01 to 2019-12-31).

    Usage:
        ./backfill_isslis.py --dry-run                       # full range, no download
        ./backfill_isslis.py --start-date 2019-12-01 --end-date 2019-12-31
        ./backfill_isslis.py                                 # full backfill
"""

import argparse
import re
import shutil
from datetime import date, timedelta
from pathlib import Path

import earthaccess

from scintilla.common.defines import ISSLIS_RAW_DIR, MISSION_TO_EARTHDATA_DICT

FILENAME_DATE_RE = re.compile(r'ISS_LIS_SC_V\d\.\d_(\d{8})_\d{6}_FIN\.(?:nc|hdf)')


def parse_filename_date(filename):
    """Extract YYYYMMDD from an ISS LIS filename → date object, or None."""
    m = FILENAME_DATE_RE.match(Path(filename).name)
    if not m:
        return None
    yyyymmdd = m.group(1)
    return date(int(yyyymmdd[:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:8]))


def already_filed(filename, root):
    """Has this filename already been downloaded into the YMD layout?"""
    d = parse_filename_date(filename)
    if d is None:
        return False
    return (root / str(d.year) / str(d.month) / str(d.day) / Path(filename).name).exists()


def file_into_ymd(staged_path, root):
    """Move staged_path into root/<Y>/<M>/<D>/ based on its filename date."""
    d = parse_filename_date(staged_path.name)
    if d is None:
        print(f"  WARN: cannot parse date from {staged_path.name}, leaving in place")
        return None
    dest_dir = root / str(d.year) / str(d.month) / str(d.day)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / staged_path.name
    if dest.exists():
        staged_path.unlink()
        return dest
    shutil.move(str(staged_path), str(dest))
    return dest


def month_iter(start, end):
    """Yield (month_start, month_end) tuples covering [start, end]."""
    cur = date(start.year, start.month, 1)
    while cur <= end:
        if cur.month == 12:
            next_month = date(cur.year + 1, 1, 1)
        else:
            next_month = date(cur.year, cur.month + 1, 1)
        month_end = min(next_month - timedelta(days=1), end)
        yield max(cur, start), month_end
        cur = next_month


def main(start_date='2017-03-01', end_date='2019-12-31', dry_run=False):
    earthaccess.login(strategy='netrc')

    isslis = MISSION_TO_EARTHDATA_DICT['ISSLIS']
    short_name = isslis['short_name']
    version = isslis['version']
    print(f"ISSLIS dataset: short_name={short_name}, version={version}")

    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    print(f"Date range: {start} → {end}")

    staging = ISSLIS_RAW_DIR / "_backfill_staging"
    staging.mkdir(parents=True, exist_ok=True)

    total_found = 0
    total_unique = 0
    total_skipped = 0
    total_filed = 0
    total_failed = 0

    for month_start, month_end in month_iter(start, end):
        print(f"\n=== {month_start.isoformat()} → {month_end.isoformat()} ===")

        try:
            results = earthaccess.search_data(
                short_name=short_name,
                version=version,
                temporal=(month_start.isoformat(), month_end.isoformat()),
            )
        except Exception as e:
            print(f"  search failed: {e}")
            continue

        n_found = len(results)
        total_found += n_found

        # v3 CMR registers each orbit as two granules (.nc and .hdf). Dedupe
        # by orbit stem, preferring .nc to match the existing on-disk convention.
        unique_by_stem = {}
        for r in results:
            urls = r.data_links()
            if not urls:
                continue
            fname = Path(urls[0]).name
            stem, _, ext = fname.rpartition('.')
            existing = unique_by_stem.get(stem)
            if existing is None:
                unique_by_stem[stem] = r
            else:
                existing_ext = Path(existing.data_links()[0]).name.rpartition('.')[2]
                if existing_ext == 'hdf' and ext == 'nc':
                    unique_by_stem[stem] = r

        unique_granules = list(unique_by_stem.values())
        n_unique = len(unique_granules)
        total_unique += n_unique

        to_download = []
        skipped_this_month = 0
        for r in unique_granules:
            fname = Path(r.data_links()[0]).name
            if already_filed(fname, ISSLIS_RAW_DIR):
                skipped_this_month += 1
                continue
            to_download.append(r)

        total_skipped += skipped_this_month
        print(f"  found: {n_found} ({n_unique} unique orbits)  already on disk: {skipped_this_month}  to download: {len(to_download)}")

        if dry_run or not to_download:
            continue

        try:
            files = earthaccess.download(to_download, str(staging))
        except Exception as e:
            print(f"  download failed: {e}")
            total_failed += len(to_download)
            continue

        filed_this_month = 0
        for f in files:
            if f is None:
                total_failed += 1
                continue
            filed = file_into_ymd(Path(f), ISSLIS_RAW_DIR)
            if filed is not None:
                filed_this_month += 1
                total_filed += 1
        print(f"  filed: {filed_this_month}")

    leftovers = list(staging.glob("*.nc"))
    if leftovers:
        print(f"\nWARN: {len(leftovers)} files left in staging dir {staging}")
    else:
        try:
            staging.rmdir()
        except OSError:
            pass

    print("\n=== Summary ===")
    print(f"Granules found:     {total_found}")
    print(f"Unique orbits:      {total_unique}  (after deduping .nc/.hdf pairs)")
    print(f"Already on disk:    {total_skipped}")
    print(f"Downloaded + filed: {total_filed}")
    print(f"Failed:             {total_failed}")


def parse_opt():
    parser = argparse.ArgumentParser(description="Download missing ISS LIS .nc files")
    parser.add_argument('--start-date', type=str, default='2017-03-01',
                        help='inclusive start date YYYY-MM-DD (default: 2017-03-01)')
    parser.add_argument('--end-date', type=str, default='2019-12-31',
                        help='inclusive end date YYYY-MM-DD (default: 2019-12-31)')
    parser.add_argument('--dry-run', action='store_true',
                        help='search and report counts without downloading')
    return parser.parse_args()


if __name__ == "__main__":
    opt = parse_opt()
    main(**vars(opt))

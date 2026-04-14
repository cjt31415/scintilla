#!/usr/bin/env python
"""
    find_isslis_overlaps.py - discover which AOIs have ISS LIS lightning flashes

    Phase 1 (--rebuild-index): Scan all raw ISS LIS NetCDF files, extract
        flash lat/lon/time, save as a parquet index for fast querying.

    Phase 2 (default): Load the index, spatially filter against each AOI,
        report dates and flash counts.

    Usage:
        ./find_isslis_overlaps.py --rebuild-index
        ./find_isslis_overlaps.py
        ./find_isslis_overlaps.py --aoi tucson
        ./find_isslis_overlaps.py --aoi tucson --output-format csv
"""

import argparse
from datetime import datetime

import netCDF4
import numpy as np
import pandas as pd
import pytz
import shapely.vectorized
from shapely.geometry import shape
from tqdm import tqdm

from scintilla.common.defines import ISSLIS_RAW_DIR
from scintilla.common.utils import aoi_list, geometry_gdf_to_json, get_aoi_timezone, load_geometry

INDEX_PATH = ISSLIS_RAW_DIR / "isslis_flash_index.parquet"
TAI93_EPOCH = datetime(1993, 1, 1)


def extract_flashes_lightweight(nc_path):
    """Extract just lat, lon, time from an ISS LIS NetCDF file.

    Returns a dict of arrays (not a DataFrame) for speed during index building.
    Returns None if the file has no flashes.
    """
    try:
        ds = netCDF4.Dataset(nc_path, 'r')

        # Some orbits have zero flashes — the variable won't exist
        if 'lightning_flash_lat' not in ds.variables:
            ds.close()
            return None

        lat = ds.variables['lightning_flash_lat'][:]
        lon = ds.variables['lightning_flash_lon'][:]
        tai93_time = ds.variables['lightning_flash_TAI93_time'][:]
        ds.close()

        if len(lat) == 0:
            return None

        # Convert TAI93 seconds to Unix timestamps (faster than datetime objects)
        tai93_offset = (TAI93_EPOCH - datetime(1970, 1, 1)).total_seconds()
        unix_times = tai93_time + tai93_offset

        return {
            'latitude': np.array(lat, dtype=np.float32),
            'longitude': np.array(lon, dtype=np.float32),
            'timestamp': unix_times.astype(np.float64),
        }
    except Exception as e:
        print(f"  Error reading {nc_path.name}: {e}")
        return None


def build_index():
    """Scan all ISS LIS .nc/.hdf files and build a parquet index of flash locations."""
    nc_files = sorted(
        list(ISSLIS_RAW_DIR.rglob("*.nc")) + list(ISSLIS_RAW_DIR.rglob("*.hdf"))
    )
    print(f"Scanning {len(nc_files)} ISS LIS files in {ISSLIS_RAW_DIR}")

    all_lat = []
    all_lon = []
    all_ts = []
    files_with_flashes = 0
    files_empty = 0

    for nc_path in tqdm(nc_files, desc="Building index"):
        result = extract_flashes_lightweight(nc_path)
        if result is not None:
            all_lat.append(result['latitude'])
            all_lon.append(result['longitude'])
            all_ts.append(result['timestamp'])
            files_with_flashes += 1
        else:
            files_empty += 1

    if not all_lat:
        print(f"No flashes found in any of {len(nc_files)} files under {ISSLIS_RAW_DIR}.")
        print("Nothing to index. Check that ISS LIS .nc/.hdf files are present and contain lightning_flash_lat variables.")
        return

    lat = np.concatenate(all_lat)
    lon = np.concatenate(all_lon)
    ts = np.concatenate(all_ts)

    df = pd.DataFrame({
        'latitude': lat,
        'longitude': lon,
        'timestamp': ts,
    })

    # Convert unix timestamp to datetime for easier querying
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='s', utc=True)
    df = df.drop(columns=['timestamp'])

    df.to_parquet(INDEX_PATH, index=False)

    print(f"\n{len(df):,} flashes indexed from {files_with_flashes:,} files "
          f"({files_empty:,} empty)")
    print(f"Date range: {df['datetime'].min()} to {df['datetime'].max()}")
    print(f"Index saved to {INDEX_PATH} ({INDEX_PATH.stat().st_size / 1024 / 1024:.1f} MB)")


def load_index():
    """Load the flash index from parquet."""
    if not INDEX_PATH.exists():
        print(f"Index not found at {INDEX_PATH}")
        print("Run with --rebuild-index first")
        raise SystemExit(1)

    return pd.read_parquet(INDEX_PATH)


def filter_flashes_to_aoi(df, aoi_name):
    """Filter a flash DataFrame to rows whose (longitude, latitude) lies
    inside the named AOI's polygon.

    Expects `df` to have 'latitude' and 'longitude' columns. Two-stage
    filter: vectorized bbox first, then vectorized point-in-polygon via
    shapely.vectorized.contains (single C call against numpy arrays — no
    per-row Python apply). Returns an empty DataFrame if no flashes match.
    """
    aoi_gdf = load_geometry(aoi_name)
    aoi_geom_json = geometry_gdf_to_json(aoi_gdf)

    # Bbox pre-filter (fast, vectorized in pandas)
    coords = aoi_geom_json['coordinates'][0]
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)

    candidates = df[
        (df['latitude'] >= min_lat) & (df['latitude'] <= max_lat) &
        (df['longitude'] >= min_lon) & (df['longitude'] <= max_lon)
    ]

    if len(candidates) == 0:
        return candidates.iloc[0:0]   # empty with same columns

    polygon = shape(aoi_geom_json)
    inside_mask = shapely.vectorized.contains(
        polygon,
        candidates['longitude'].to_numpy(),
        candidates['latitude'].to_numpy(),
    )
    return candidates[inside_mask].copy()


def query_aoi(df, aoi_name):
    """Find flashes within an AOI, return summary by date in local time."""
    matches = filter_flashes_to_aoi(df, aoi_name)
    if len(matches) == 0:
        return pd.DataFrame()

    local_tz_str = get_aoi_timezone(aoi_name)
    local_tz = pytz.timezone(local_tz_str)

    # Convert to local time for grouping and display
    matches['local_dt'] = matches['datetime'].dt.tz_convert(local_tz)
    matches['local_date'] = matches['local_dt'].dt.date

    summary = matches.groupby('local_date').agg(
        flashes=('latitude', 'count'),
        first_flash=('local_dt', 'min'),
        last_flash=('local_dt', 'max'),
        first_utc=('datetime', 'min'),
        last_utc=('datetime', 'max'),
    ).reset_index()

    tz_abbr = matches['local_dt'].iloc[0].strftime('%Z')

    summary['time_range'] = summary.apply(
        lambda r: (f"{r['first_flash'].strftime('%H:%M')}-{r['last_flash'].strftime('%H:%M')} {tz_abbr}"
                   f"  ({r['first_utc'].strftime('%H:%M')}-{r['last_utc'].strftime('%H:%M')} UTC)"),
        axis=1
    )
    summary['tz'] = local_tz_str

    return summary[['local_date', 'flashes', 'time_range', 'tz']].rename(columns={'local_date': 'date'})


def discover(df, mode='all-time', min_flashes=100, top=20,
             year=None, bbox=None, exclude_existing_aois=True):
    """Find high-density flash clusters that aren't already covered by an AOI.

    Bins flashes into 1°×1° cells. In `all-time` mode, sums across the whole
    parquet (good for finding persistent hotspots like Catatumbo). In `by-day`
    mode, groups by (date, cell) (good for finding specific storm-day events
    to animate).

    Cells whose center falls inside any existing AOI's bounding box are
    dropped when `exclude_existing_aois=True`, so the output is *new*
    candidates rather than rediscoveries.

    Returns a DataFrame ordered by flash count descending, top-N rows.
    """
    work = df

    if year is not None:
        work = work[work['datetime'].dt.year == year]

    if bbox is not None:
        west, south, east, north = bbox
        work = work[
            (work['longitude'] >= west) & (work['longitude'] <= east) &
            (work['latitude'] >= south) & (work['latitude'] <= north)
        ]

    if len(work) == 0:
        return pd.DataFrame()

    work = work.assign(
        lat_bin=np.floor(work['latitude']).astype(int),
        lon_bin=np.floor(work['longitude']).astype(int),
    )

    if mode == 'by-day':
        work = work.assign(date=work['datetime'].dt.date)
        grouped = work.groupby(['date', 'lat_bin', 'lon_bin']).size().reset_index(name='flashes')
    else:
        grouped = work.groupby(['lat_bin', 'lon_bin']).size().reset_index(name='flashes')

    grouped = grouped[grouped['flashes'] >= min_flashes]
    if len(grouped) == 0:
        return pd.DataFrame()

    grouped['lat'] = grouped['lat_bin'] + 0.5
    grouped['lon'] = grouped['lon_bin'] + 0.5
    grouped = grouped.drop(columns=['lat_bin', 'lon_bin'])

    if exclude_existing_aois:
        aoi_bboxes = []
        for name in aoi_list():
            try:
                gdf = load_geometry(name)
            except FileNotFoundError:
                continue
            minx, miny, maxx, maxy = gdf.total_bounds
            aoi_bboxes.append((minx, miny, maxx, maxy))

        if aoi_bboxes:
            def covered(row):
                lat, lon = row['lat'], row['lon']
                for minx, miny, maxx, maxy in aoi_bboxes:
                    if minx <= lon <= maxx and miny <= lat <= maxy:
                        return True
                return False
            grouped = grouped[~grouped.apply(covered, axis=1)]

    grouped = grouped.sort_values('flashes', ascending=False).head(top)

    grouped['suggested_aoi_name'] = grouped.apply(
        lambda r: f"discover_{r['lat']:+.1f}_{r['lon']:+.1f}", axis=1
    )

    if mode == 'by-day':
        return grouped[['date', 'lat', 'lon', 'flashes', 'suggested_aoi_name']].reset_index(drop=True)
    return grouped[['lat', 'lon', 'flashes', 'suggested_aoi_name']].reset_index(drop=True)


def main(rebuild_index=False, aoi=None, output_format='table',
         discover_mode=False, mode='all-time', min_flashes=100, top=20,
         year=None, bbox=None, include_existing=False):
    if rebuild_index:
        build_index()
        return

    if discover_mode:
        df = load_index()
        print(f"Index loaded: {len(df):,} flashes, "
              f"{df['datetime'].min().strftime('%Y-%m-%d')} to "
              f"{df['datetime'].max().strftime('%Y-%m-%d')}")

        results = discover(df, mode=mode, min_flashes=min_flashes, top=top,
                           year=year, bbox=bbox,
                           exclude_existing_aois=not include_existing)

        if len(results) == 0:
            print("\nNo cells matched the discovery filters.")
            return

        if output_format == 'csv':
            print(results.to_csv(index=False))
        else:
            print(f"\nTop {len(results)} flash hotspots ({mode}, "
                  f"min {min_flashes} flashes"
                  f"{', existing AOIs excluded' if not include_existing else ''}):")
            if mode == 'by-day':
                print(f"\n{'Date':<12} {'Lat':>8} {'Lon':>9} {'Flashes':>8}  {'Suggested AOI name'}")
                print("-" * 70)
                for _, r in results.iterrows():
                    print(f"{str(r['date']):<12} {r['lat']:>+8.1f} {r['lon']:>+9.1f} "
                          f"{r['flashes']:>8}  {r['suggested_aoi_name']}")
            else:
                print(f"\n{'Lat':>8} {'Lon':>9} {'Flashes':>10}  {'Suggested AOI name'}")
                print("-" * 60)
                for _, r in results.iterrows():
                    print(f"{r['lat']:>+8.1f} {r['lon']:>+9.1f} {r['flashes']:>10,}  "
                          f"{r['suggested_aoi_name']}")
        return

    df = load_index()
    print(f"Index loaded: {len(df):,} flashes, "
          f"{df['datetime'].min().strftime('%Y-%m-%d')} to "
          f"{df['datetime'].max().strftime('%Y-%m-%d')}")

    # Determine which AOIs to query
    aois = [aoi] if aoi else aoi_list()

    all_results = []

    for aoi_name in aois:
        summary = query_aoi(df, aoi_name)
        if len(summary) > 0:
            summary.insert(0, 'aoi', aoi_name)
            all_results.append(summary)

    if not all_results:
        print("\nNo ISS LIS flashes found in any AOI.")
        return

    results = pd.concat(all_results, ignore_index=True)
    results = results.sort_values(['aoi', 'date']).reset_index(drop=True)

    if output_format == 'csv':
        print(results.to_csv(index=False))
    else:
        # Table format — local time is primary, UTC in parentheses
        print(f"\n{'AOI':<20} {'Local Date':<12} {'Flashes':>8}  {'Time Range (local + UTC)'}")
        print("-" * 85)
        for _, row in results.iterrows():
            print(f"{row['aoi']:<20} {row['date']}  {row['flashes']:>7}  {row['time_range']}")

        # Summary
        total_aois = results['aoi'].nunique()
        total_days = len(results)
        total_flashes = results['flashes'].sum()
        print(f"\n{total_flashes:,} flashes across {total_days} AOI-days in {total_aois} AOIs")
        if total_aois == 1:
            print(f"Times shown in {results['tz'].iloc[0]}")


def parse_opt():
    parser = argparse.ArgumentParser(
        description="Find ISS LIS flash overlaps with AOIs (or discover new hotspots)")
    parser.add_argument('--rebuild-index', action='store_true',
                        help='scan all ISS LIS .nc files and rebuild the flash index')
    parser.add_argument('--aoi', type=str, choices=aoi_list(),
                        help='query a specific AOI (default: all)')
    parser.add_argument('--output-format', type=str, choices=['table', 'csv'],
                        default='table', help='output format (default: table)')

    parser.add_argument('--discover', dest='discover_mode', action='store_true',
                        help='find new lightning hotspots not yet covered by an AOI')
    parser.add_argument('--mode', type=str, choices=['all-time', 'by-day'],
                        default='all-time',
                        help="discover mode: 'all-time' for persistent hotspots, "
                             "'by-day' for single-day storm events")
    parser.add_argument('--min-flashes', type=int, default=100,
                        help='minimum flashes per cell to include (default: 100)')
    parser.add_argument('--top', type=int, default=20,
                        help='number of top hotspots to return (default: 20)')
    parser.add_argument('--year', type=int,
                        help='filter discovery to a single year')
    parser.add_argument('--bbox', type=float, nargs=4, metavar=('W', 'S', 'E', 'N'),
                        help='filter discovery to a bounding box (lon/lat in WGS84)')
    parser.add_argument('--include-existing', action='store_true',
                        help='include cells already covered by an existing AOI bbox')
    return parser.parse_args()


if __name__ == "__main__":
    opt = parse_opt()
    main(**vars(opt))

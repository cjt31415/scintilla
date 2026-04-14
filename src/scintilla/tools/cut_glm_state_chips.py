#!/usr/bin/env python
"""
    cut_glm_state_chips.py - clip raw GLM .nc files to one or more US states.

    Single state -> clipped to that state's polygon.
    Multiple states -> clipped to the bounding box of the union (handles
    non-contiguous selections cleanly and includes lightning between states).

    Thin CLI wrapper around scintilla.tools.cut_glm_aoi_chips.ensure_chips.
"""

import argparse

import geopandas as gpd
from shapely.geometry import box

from scintilla.common.defines import GIS_DIR
from scintilla.common.utils import (
    clean_state_name,
    format_time_display,
    parse_date_range,
    state_abbr,
    validate_state_name,
)
from scintilla.tools.cut_glm_aoi_chips import ensure_chips


def build_states_clip_region(states):
    """For a list of US state names (case-insensitive), return
    `(canonical_states, out_name, clip_gdf)`:

      - canonical-cased state names from the shapefile
      - output sub-directory name under GLM_CLIP_DIR (single: snake_case;
        multi: alphabetical "AZ-NM-TX" abbreviation)
      - clip GeoDataFrame (single: state polygon; multi: bbox of union)
    """
    states_shape_path = GIS_DIR / "cb_2018_us_state_5m.zip"
    us_state_borders_gdf = gpd.read_file(states_shape_path)

    canonical = [validate_state_name(us_state_borders_gdf, s) for s in states]
    state_border_gdf = us_state_borders_gdf[us_state_borders_gdf['NAME'].isin(canonical)]

    if len(canonical) == 1:
        out_name = clean_state_name(canonical[0])
        clip_gdf = state_border_gdf
    else:
        out_name = "-".join(sorted([state_abbr(s) for s in canonical]))
        minx, miny, maxx, maxy = state_border_gdf.total_bounds
        clip_gdf = gpd.GeoDataFrame(
            {'geometry': [box(minx, miny, maxx, maxy)]},
            crs=state_border_gdf.crs,
        )

    return canonical, out_name, clip_gdf


def main(states=None,
        start_date=None,
        end_date=None,
        max_items=None,
        goes_satellite='G18',
        utc=False):

    start_dt_utc, end_dt_utc, local_tz = parse_date_range(start_date, end_date, aoi=None, utc=utc)
    if end_dt_utc <= start_dt_utc:
        raise ValueError("start-date should be < end-date")
    print(f"Date range: {format_time_display(start_dt_utc, local_tz)} → {format_time_display(end_dt_utc, local_tz)}")

    canonical, out_name, clip_gdf = build_states_clip_region(states)
    if len(canonical) > 1:
        print(f"multi-state: clipping to bounding box of {', '.join(canonical)}")

    ensure_chips(
        out_name=out_name,
        clip_gdf=clip_gdf,
        start_dt_utc=start_dt_utc,
        end_dt_utc=end_dt_utc,
        goes_satellite=goes_satellite,
        max_items=max_items,
    )


def parse_opt():
    parser = argparse.ArgumentParser()
    parser.add_argument('--states', type=str, nargs='+', required=True, help='one or more US state names (case-insensitive)')
    parser.add_argument('--start-date', type=str, required=True, help='start-date of search')
    parser.add_argument('--end-date', type=str, help="end-date of search; defaults to today")
    parser.add_argument('--max-items', type=int, default=1, help="cut first max-items from sorted file list. Skips previously cut but counts them.")
    parser.add_argument('--goes-satellite', type=str, choices=['G16', 'G17', 'G18'], default='G18', help='NOAA GOES satellite -> part of raw input dir')
    parser.add_argument('--utc', action='store_true', help='interpret dates as UTC (default: local timezone of states region)')
    return parser.parse_args()


if __name__ == "__main__":
    opt = parse_opt()
    main(**vars(opt))

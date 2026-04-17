#!/usr/bin/env python
"""
    movie_map.py - for a given timeframe, create a time-lapse of GLM lightning maps

    Create the background upfront then pass that to the frame-by-frame rendering.
"""
import argparse
import io
import math
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import cartopy.crs as ccrs
import ffmpeg
import matplotlib.pyplot as plt
import pandas as pd
import psutil
import rasterio
from pyproj import Transformer

from scintilla.animate.movie_frame_map import make_map
from scintilla.common.defines import DATA_DIR, GLM_CLIP_DIR, GLM_POLYGON_DIR
from scintilla.common.map_utils import map_background
from scintilla.common.utils import (
    aoi_area_in_km2,
    aoi_list,
    find_files,
    format_time_display,
    format_time_short,
    geometry_gdf_to_json,
    load_geometry,
    parse_date_range,
)
from scintilla.tools.cut_glm_aoi_chips import ensure_chips
from scintilla.tools.cut_glm_state_chips import build_states_clip_region

TMP_DIR = Path("/tmp/ffmpeg")
FRAME_FORMAT = 'jpg'

# Output profiles: target long-edge pixel count + DPI.
# Final frame dimensions are derived from the AOI's actual aspect ratio at
# render time (see compute_fig_size). A 16:9 AOI under the mp4 profile yields
# 1920×1080. A 1:1 AOI under the mp4 profile yields 1080×1080. A 4:3 AOI
# yields 1920×1440. Whatever the AOI bbox says.
OUTPUT_PROFILES = {
    'mp4': {'long_edge_px': 1920, 'frame_dpi': 120},
    'gif': {'long_edge_px': 800,  'frame_dpi': 50},
}


def simplify_title(region_name: str,
                   start_dt_utc: datetime,
                   end_dt_utc: datetime,
                   tz_str: str) -> str:
    """Build a movie title with one timezone label, collapsing the end date
    when both endpoints fall on the same local day.

        same day:  "Us-Mexico-Iss 2023-07-31 21:10 to 21:30 (MST)"
        diff day:  "Us-Mexico-Iss 2023-07-31 23:30 to 2023-08-01 02:15 (MST)"
    """
    import pytz as _pytz
    tz = _pytz.timezone(tz_str)
    s = start_dt_utc.astimezone(tz)
    e = end_dt_utc.astimezone(tz)
    tz_abbr = s.strftime('%Z')
    region = region_name.replace('-', ' ').replace('_', ' ').title()
    if s.date() == e.date():
        return f"{region} {s:%Y-%m-%d %H:%M} to {e:%H:%M} ({tz_abbr})"
    return f"{region} {s:%Y-%m-%d %H:%M} to {e:%Y-%m-%d %H:%M} ({tz_abbr})"


def simplified_datetime_string(dt: datetime) -> str:
    if dt.hour == 23:
        dt += timedelta(days=1)
        dt = dt.replace(hour=0, minute=0, second=0)

    if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
        return dt.strftime('%Y-%m-%d')
    else:
        return dt.strftime('%Y-%m-%d_%H%M')


def get_memory_usage():
    process = psutil.Process(os.getpid())
    return process.memory_info().rss


def fetch_background_image(provider, map_extent, zoom_level, fig_size, frame_dpi):
    """Render the map background tiles to a clean PNG with no axes/margins.

    The image contains only the map tiles, cropped tightly. It will be
    stretched to fill the map axes in each frame via ax.imshow(extent=...).
    Rendered at 2x frame_dpi so tile detail survives the imshow resampling.
    """
    crs = ccrs.PlateCarree()
    bg_dpi = frame_dpi * 2
    fig, ax = plt.subplots(figsize=fig_size, subplot_kw={'projection': crs}, dpi=bg_dpi)

    ax.set_extent(map_extent)
    ax.axis('off')

    print(f"Mother map_extent (includes all points): {map_extent}")

    if provider is not None:
        ax.add_image(provider, zoom_level)
    else:
        ax.set_facecolor('white')

    img_bytes = io.BytesIO()
    plt.savefig(img_bytes, bbox_inches='tight', pad_inches=0, dpi=bg_dpi, format='png')
    plt.close(fig)

    return img_bytes.getvalue()


def aoi_to_extent(aoi_geom):
    """Convert a GeoJSON polygon to a cartopy extent [left, right, bottom, top]."""
    coordinates = aoi_geom['coordinates'][0]
    lons = [coord[0] for coord in coordinates]
    lats = [coord[1] for coord in coordinates]
    return [min(lons), max(lons), min(lats), max(lats)]


def aoi_aspect_from_extent(map_extent):
    """Width/height aspect from PlateCarree extent [W, E, S, N]."""
    w = map_extent[1] - map_extent[0]
    h = map_extent[3] - map_extent[2]
    return w / h


def compute_frame_dims(aoi_aspect, long_edge_px, dpi):
    """Derive frame dimensions and matching fig_size from AOI aspect.

    Returns (pixel_w, pixel_h, fig_size_in_inches). Pixel dimensions are
    rounded to even integers — h.264 (and many other codecs) require even
    width and height.
    """
    if aoi_aspect >= 1:
        pixel_w = long_edge_px
        pixel_h = round(long_edge_px / aoi_aspect)
    else:
        pixel_h = long_edge_px
        pixel_w = round(long_edge_px * aoi_aspect)
    if pixel_w % 2:
        pixel_w += 1
    if pixel_h % 2:
        pixel_h += 1
    fig_size = (pixel_w / dpi, pixel_h / dpi)
    return pixel_w, pixel_h, fig_size


def warn_if_mp4_not_169(aoi_aspect, output_format, region_name):
    """Soft note when MP4 + non-16:9 AOI. Non-blocking — render proceeds."""
    if output_format != 'mp4':
        return
    target = 16 / 9
    if abs(aoi_aspect - target) / target <= 0.05:
        return
    print(f"NOTE: AOI '{region_name}' aspect is {aoi_aspect:.2f}; "
          f"MP4 outputs are typically 16:9 ({target:.2f}) for video platforms.")
    print(f"      To snap to 16:9 first: "
          f"./src/scintilla/tools/aoi_snap_aspect.py --aoi {region_name} --aspect 16:9")


def gdf_to_extent(gdf):
    """Convert a GeoDataFrame to a cartopy extent [left, right, bottom, top]."""
    if gdf.empty:
        raise ValueError("The GeoDataFrame is empty.")
    minx, miny, maxx, maxy = gdf.total_bounds
    return [minx, maxx, miny, maxy]


def glm_clip_extent(glm_path):
    """Get the WGS84 extent of a GLM GeoTIFF chip."""
    with rasterio.open(glm_path) as src:
        src_proj = src.crs
        dest_proj = 'EPSG:4326'
        transformer = Transformer.from_crs(src_proj, dest_proj, always_xy=True)

        left, bottom, right, top = src.bounds
        left_lon, bottom_lat = transformer.transform(left, bottom)
        right_lon, top_lat = transformer.transform(right, top)

        return [left_lon, right_lon, bottom_lat, top_lat]


def area_to_zoom(area_km2):
    """Heuristic: estimate cartopy zoom level from area in km².

    Calibrated so Arizona (~295,000 km²) → zoom 8, Tucson (~156 km²) → zoom 13.
    Each factor-of-4 change in area shifts zoom by 1 level.
    """
    base_area_km2 = 295203.37  # Arizona
    base_zoom = 8

    if area_km2 > base_area_km2:
        area_ratio = area_km2 / base_area_km2
        zoom_adjustment = -math.log(area_ratio, 4)
    else:
        area_ratio = base_area_km2 / area_km2
        zoom_adjustment = math.log(area_ratio, 4)

    estimated_zoom = base_zoom + zoom_adjustment

    return round(estimated_zoom)


def load_isslis_flashes(aoi, start_dt_utc, end_dt_utc):
    """Load ISS LIS flash data from the parquet index, filtered to AOI and
    date range, with columns renamed for the per-frame renderer.

    Uses the index built by find_isslis_overlaps.py --rebuild-index, then
    delegates the spatial filter to filter_flashes_to_aoi.

    Returns a DataFrame with columns: flash_latitude, flash_longitude, datetime.
    Returns None if no data found.
    """
    from scintilla.common.defines import ISSLIS_RAW_DIR
    from scintilla.tools.find_isslis_overlaps import filter_flashes_to_aoi

    index_path = ISSLIS_RAW_DIR / "isslis_flash_index.parquet"
    if not index_path.exists():
        print("ISS LIS index not found. Run: find_isslis_overlaps.py --rebuild-index")
        return None

    df = pd.read_parquet(index_path)

    # Date range filter first — cheap, applied to the whole index.
    df = df[(df['datetime'] >= start_dt_utc) & (df['datetime'] <= end_dt_utc)]
    if len(df) == 0:
        return None

    matches = filter_flashes_to_aoi(df, aoi)
    if len(matches) == 0:
        return None

    return matches.rename(
        columns={'latitude': 'flash_latitude', 'longitude': 'flash_longitude'}
    ).reset_index(drop=True)


def map_movie(
        aoi=None,
        states=None,
        start_date=None,
        end_date=None,
        delta_t=None,
        framerate=None,
        background='google',
        output_format='mp4',
        layers=None,
        utc=False,
        use_polygons=False,
        show_tod=False,
        show_grid=False,
        goes_satellite='G18',
        skip_cut=False,
        debug=False,
        **kwargs):

    import pytz as _pytz

    background_name = background
    profile = OUTPUT_PROFILES[output_format]
    long_edge_px = profile['long_edge_px']
    frame_dpi = profile['frame_dpi']
    # fig_size is derived below from (aoi_aspect, long_edge_px, frame_dpi)
    # once map_extent is known.

    # Determine timezone from AOI or states
    aoi_for_tz = aoi  # states will be resolved later
    start_dt_utc, end_dt_utc, local_tz = parse_date_range(start_date, end_date, aoi=aoi_for_tz, utc=utc)
    print(f"Date range: {format_time_display(start_dt_utc, local_tz)} → {format_time_display(end_dt_utc, local_tz)}")

    # Make the end inclusive for chip lookup so the requested end timestamp
    # produces a frame (find_files filters [start, end)). Title still shows
    # the user-provided end.
    end_dt_utc_inclusive = end_dt_utc + timedelta(seconds=1)

    # Determine which data layers to render up front — chip-cutting and
    # chip-finding only run when GLM is requested. ISS-only mode skips both.
    if layers is None:
        layers = ['glm']
    show_glm = 'glm' in layers
    show_isslis = 'isslis' in layers

    # -----------------------------------------------------------------------
    # Determine region from --aoi or --states
    if aoi:
        region_name = aoi
        aoi_gdf = load_geometry(aoi)
        if len(aoi_gdf) != 1:
            raise ValueError("This code only understands simple geometries")
        aoi_geom_json = geometry_gdf_to_json(aoi_gdf)
        map_extent = aoi_to_extent(aoi_geom_json)

        area = aoi_area_in_km2(aoi_gdf)
        print(f"area of [{aoi}] AOI is approximately {round(area, 2)} km^2")

        clip_dir = GLM_CLIP_DIR / aoi
        print(f"goes_dir: {clip_dir}")

        if show_glm and not skip_cut:
            stats = ensure_chips(aoi, aoi_gdf, start_dt_utc, end_dt_utc_inclusive,
                                 goes_satellite=goes_satellite, verbose=False)
            print(f"chips: {stats['cut']} cut, {stats['skipped']} already present "
                  f"({stats['raw_found']} raw .nc files)")

        gpkg_path = GLM_POLYGON_DIR / aoi / f"{aoi}_{start_date}_{end_date}_hour.gpkg"
        print(f"gpkg: {gpkg_path}")

    else:
        # Canonicalize state names, build clean_state output dir name, and
        # build clip_gdf (state polygon for single, bbox of union for multi).
        # Shared with the cut_glm_state_chips CLI tool.
        states, clean_state, clip_gdf = build_states_clip_region(states)
        region_name = clean_state
        clip_dir = GLM_CLIP_DIR / clean_state
        print(f"goes_dir: {clip_dir}")

        if len(states) > 1:
            print(f"multi-state: clipping to bounding box of {', '.join(states)}")

        map_extent = gdf_to_extent(clip_gdf)
        area = aoi_area_in_km2(clip_gdf)
        print(f"area of [{', '.join(states)}] is approximately {round(area, 2)} km^2")

        if show_glm and not skip_cut:
            stats = ensure_chips(clean_state, clip_gdf,
                                 start_dt_utc, end_dt_utc_inclusive,
                                 goes_satellite=goes_satellite, verbose=False)
            print(f"chips: {stats['cut']} cut, {stats['skipped']} already present "
                  f"({stats['raw_found']} raw .nc files)")

        gpkg_path = GLM_POLYGON_DIR / clean_state / f"{clean_state}_{start_date}_{end_date}_hour.gpkg"
        print(f"gpkg: {gpkg_path}")

    # -----------------------------------------------------------------------
    # Derive frame dimensions from the AOI's actual bbox aspect (render what
    # we're given — the AOI's shape is the user's expressed framing intent).
    aoi_aspect = aoi_aspect_from_extent(map_extent)
    pixel_w, pixel_h, fig_size = compute_frame_dims(aoi_aspect, long_edge_px, frame_dpi)
    print(f"Output: {output_format} ({pixel_w}×{pixel_h}, AOI aspect {aoi_aspect:.2f})")
    warn_if_mp4_not_169(aoi_aspect, output_format, region_name)

    # -----------------------------------------------------------------------
    # Build the per-frame time list. With GLM, frames are driven by the
    # actual chip files on disk. Without GLM (ISS-only), synthesize a
    # 1-minute-cadence list spanning the requested date range; the existing
    # delta_t thinning loop further thins it if delta_t > 1.
    if show_glm:
        print(f"goes_dir: {clip_dir}")
        path_list_dicts = find_files(clip_dir, start_dt_utc, end_dt_utc_inclusive, ext='tif', return_by='dict')

        if not path_list_dicts:
            print(f"No GLM files found in {clip_dir} for date range {start_date} - {end_date}")
            sys.exit(1)

        goes_map_extent = glm_clip_extent(path_list_dicts[0]['path'])
        print(f"map_extent: {map_extent}")
        print(f" vs. goes_map_extent: {goes_map_extent}")
    else:
        synthetic = []
        t = start_dt_utc
        while t <= end_dt_utc:
            synthetic.append({'dt': t, 'path': None})
            t += timedelta(minutes=1)
        path_list_dicts = synthetic
        print(f"ISS-only mode: synthesized {len(path_list_dicts)} 1-minute frame slots")
        print(f"map_extent: {map_extent}")

    # Load ISS LIS flash data (if requested)
    isslis_df = None
    if show_isslis and aoi:
        isslis_df = load_isslis_flashes(aoi, start_dt_utc, end_dt_utc)
        if isslis_df is not None:
            print(f"ISS LIS: {len(isslis_df)} flashes loaded for {aoi}")
        else:
            print(f"ISS LIS: no flash data found for {aoi} in date range")

    # -----------------------------------------------------------------------
    # Compute zoom and fetch background
    zoom_level = area_to_zoom(area)
    print(f"area = {area} => zoom level {zoom_level}")

    provider = map_background(background_name)
    if not provider:
        print("provider is None - getting white background")

    background_image = fetch_background_image(provider, map_extent, zoom_level, fig_size, frame_dpi)

    # -----------------------------------------------------------------------
    # Prepare temp directory for frames
    if TMP_DIR.exists():
        for file in TMP_DIR.glob('*'):
            file.unlink()
    else:
        TMP_DIR.mkdir(parents=True, exist_ok=True)

    # Thin the chip list by delta_t (show one frame every N minutes)
    if delta_t > 1:
        thinned = [path_list_dicts[0]]
        last_dt = path_list_dicts[0]['dt']
        for entry in path_list_dicts[1:]:
            if (entry['dt'] - last_dt).total_seconds() >= delta_t * 60:
                thinned.append(entry)
                last_dt = entry['dt']
        path_list_dicts = thinned

    total_frames = len(path_list_dicts)
    frame_digits = max(len(str(total_frames)), 4)

    print(f"Rendering {total_frames} frames (delta_t={delta_t} min, framerate={framerate} fps)")

    title = simplify_title(region_name, start_dt_utc, end_dt_utc, local_tz)

    # -----------------------------------------------------------------------
    # Render frames sequentially — one chip per frame
    param_dict = {'background_image': background_image}

    for idx, path_dict in enumerate(path_list_dicts):
        glm_path = path_dict['path']
        chip_dt = path_dict['dt']
        chip_dt_local = format_time_short(chip_dt, local_tz)

        curr_mem_use = round(get_memory_usage() / (1024 * 1024), 0)
        print(f"frame: {idx:>3}/{total_frames}  {chip_dt_local}  mem: {curr_mem_use} MB",
              end="\r", flush=True)

        # Filter ISS LIS flashes to ±1 minute of this chip's timestamp
        frame_isslis = None
        if isslis_df is not None:
            dt_window = timedelta(minutes=1)
            mask = ((isslis_df['datetime'] >= chip_dt - dt_window) &
                    (isslis_df['datetime'] <= chip_dt + dt_window))
            frame_isslis = isslis_df[mask]
            if len(frame_isslis) == 0:
                frame_isslis = None

        make_map(region=region_name,
                 background=background_name,
                 shared_dict=param_dict,
                 map_extent=map_extent,
                 zoom_level=zoom_level,
                 glm_path=glm_path if show_glm else None,
                 start_date=chip_dt_local,
                 end_date=chip_dt_local,
                 chip_dt=chip_dt.astimezone(_pytz.timezone(local_tz)),
                 title=title,
                 isslis_flashes=frame_isslis,
                 use_polygons=use_polygons,
                 gpkg_path=gpkg_path,
                 show_grid=show_grid,
                 fig_size=fig_size,
                 frame_dpi=frame_dpi,
                 save=True,
                 output_file=str(TMP_DIR / f"map_{idx:0{frame_digits}d}.{FRAME_FORMAT}"),
                 save_format=FRAME_FORMAT)

        if debug and idx > 100:
            break

    # -----------------------------------------------------------------------
    # Assemble frames into output video/gif
    dst_dir = DATA_DIR / "movies"
    dst_dir.mkdir(exist_ok=True, parents=True)

    _local_tz = _pytz.timezone(local_tz)
    sdate = simplified_datetime_string(start_dt_utc.astimezone(_local_tz).replace(tzinfo=None))
    edate = simplified_datetime_string(end_dt_utc.astimezone(_local_tz).replace(tzinfo=None))
    dst_path = dst_dir / f"{region_name}_{sdate}_{edate}.{output_format}"

    # Verify frames were rendered
    frame_files = sorted(TMP_DIR.glob(f"map_*.{FRAME_FORMAT}"))
    if not frame_files:
        print(f"Error: no frames found in {TMP_DIR}")
        sys.exit(1)
    print(f"\n{len(frame_files)} frames rendered to {TMP_DIR}")

    # Use sequential numbering pattern (more reliable than glob across platforms)
    input_pattern = str(TMP_DIR / f"map_%0{frame_digits}d.{FRAME_FORMAT}")

    if output_format == 'gif':
        # Two-pass GIF: generate optimal palette, then apply it
        palette_path = str(TMP_DIR / "palette.png")

        ffmpeg.input(input_pattern, framerate=framerate) \
              .filter('palettegen') \
              .output(palette_path) \
              .overwrite_output() \
              .run()

        input_vid = ffmpeg.input(input_pattern, framerate=framerate)
        palette = ffmpeg.input(palette_path)
        cmd = ffmpeg.filter([input_vid, palette], 'paletteuse') \
                    .output(str(dst_path), loop=0) \
                    .overwrite_output()
    else:
        cmd = ffmpeg.input(input_pattern, framerate=framerate) \
                    .output(str(dst_path)) \
                    .overwrite_output()

    ffmpeg.run(cmd)

    print(f"{idx} frames → {dst_path} ({dst_path.stat().st_size / 1024 / 1024:.1f} MB)")


def parse_opt():
    parser = argparse.ArgumentParser(description="Create GLM lightning time-lapse animation")

    region_group = parser.add_mutually_exclusive_group(required=True)
    region_group.add_argument('--aoi', type=str, choices=aoi_list(), help='name of AOI')
    region_group.add_argument('--states', type=str, nargs='+', help='one or more US state names')

    parser.add_argument('--start-date', required=True,
                        help='start datetime in AOI local time (e.g., "2023-07-30 16:00")')
    parser.add_argument('--end-date',
                        help='end datetime in AOI local time (e.g., "2023-07-30 23:00")')
    parser.add_argument('--utc', action='store_true',
                        help='interpret dates as UTC (default: AOI local time)')
    parser.add_argument('--delta-t', type=int, default=1,
                        help='time step between frames (minutes)')
    parser.add_argument('--framerate', type=int, default=4,
                        help='frames per second in output video')
    parser.add_argument('--output-format', type=str, choices=['mp4', 'gif'],
                        default='mp4', help='output format (default: mp4)')
    parser.add_argument('--background', type=str,
                        choices=['image', 'osm', 'toner', 'watercolor',
                                 'terrain-background', 'google', 'none'],
                        default='google', help='map background tile provider')
    parser.add_argument('--layers', type=str, nargs='+', choices=['glm', 'isslis'],
                        default=['glm'],
                        help='data layers to render (default: glm). Use "glm isslis" for both.')
    parser.add_argument('--use-polygons', action='store_true',
                        help='read polygon data instead of grid data')
    parser.add_argument('--show-tod', action='store_true',
                        help='vary opacity based on daytime/nighttime')
    parser.add_argument('--show-grid', action='store_true', help='draw grid lines')
    parser.add_argument('--goes-satellite', type=str, choices=['G16', 'G17', 'G18'],
                        default='G18',
                        help='GOES satellite for raw .nc lookup when auto-cutting chips')
    parser.add_argument('--skip-cut', action='store_true',
                        help='skip the ensure_chips pre-step (use only when chips already exist)')
    parser.add_argument('--debug', action='store_true', help='enable detailed diagnostics')

    return parser.parse_args()


if __name__ == "__main__":
    opt = parse_opt()
    map_movie(**vars(opt))

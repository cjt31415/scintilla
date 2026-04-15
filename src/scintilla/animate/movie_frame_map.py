#!/usr/bin/env python
"""
    movie_frame_map.py - generate a single frame for GLM lightning animation

    usage: not meant to be called separately, called by movie_map.py
"""
import argparse
import io

import cartopy.crs as ccrs
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib.image import imread
from rasterio.warp import Resampling, calculate_default_transform, reproject

DEFAULT_FIG_SIZE = (16, 9)
DEFAULT_FRAME_DPI = 120


def compute_drawn_map_bounds(fig_size, map_extent, axes_bbox):
    """Return the actual drawn-map bounds in figure coordinates, accounting
    for aspect-preservation letterboxing.

    Cartopy/matplotlib preserve the data aspect ratio when rendering a map,
    so whichever dimension doesn't match the axes aspect gets letterboxed
    (empty strips on either side). Overlays anchored to the raw axes bounds
    (like our analog clock) end up floating in the empty strips when the
    AOI aspect doesn't match the figure.

    Args:
        fig_size: (width, height) in inches, e.g. (16, 9).
        map_extent: [west, east, south, north] in PlateCarree degrees.
        axes_bbox: (left, bottom, right, top) of the Axes inside the Figure,
            in figure-fraction coordinates (what subplots_adjust produces).

    Returns:
        (left, bottom, right, top) of the drawn map in figure coordinates.
    """
    axes_l, axes_b, axes_r, axes_t = axes_bbox
    ax_w_fig = axes_r - axes_l
    ax_h_fig = axes_t - axes_b
    ax_physical_aspect = (fig_size[0] * ax_w_fig) / (fig_size[1] * ax_h_fig)

    west, east, south, north = map_extent
    data_aspect = (east - west) / (north - south)

    if data_aspect >= ax_physical_aspect:
        # Data is wider than axes — fills horizontally, letterboxed top/bottom
        map_l, map_r = axes_l, axes_r
        map_h_frac = ax_physical_aspect / data_aspect
        extra_v = (1 - map_h_frac) * ax_h_fig
        map_b = axes_b + extra_v / 2
        map_t = axes_t - extra_v / 2
    else:
        # Data is taller than axes — fills vertically, letterboxed left/right
        map_b, map_t = axes_b, axes_t
        map_w_frac = data_aspect / ax_physical_aspect
        extra_h = (1 - map_w_frac) * ax_w_fig
        map_l = axes_l + extra_h / 2
        map_r = axes_r - extra_h / 2

    return map_l, map_b, map_r, map_t


def draw_clock(ax, current_time):
    """Draw an analog clock face as a peripheral-awareness indicator.

    Design goal: the minute hand's between-frame sweep is parseable at a
    glance without stealing foveal attention from the map content. The
    face is semi-transparent so basemap terrain shows faintly behind it;
    the 12 o'clock tick is emphasized so face orientation is obvious
    without explicit hour labels.
    """
    clock_radius = 1
    # Tight bounds — no room needed for outside-the-face text labels.
    ax.set_xlim(-1.1, 1.1)
    ax.set_ylim(-1.1, 1.1)
    ax.set_aspect('equal', 'box')
    ax.axis('off')

    # Clock face: 85% opaque white so map terrain faintly shows through.
    # Opaque black outline so the clock is always clearly demarcated
    # regardless of what's behind it.
    circle = plt.Circle(
        (0, 0), clock_radius,
        edgecolor='black',
        facecolor=(1, 1, 1, 0.85),
        linewidth=1.5,
    )
    ax.add_patch(circle)

    # Tick marks. The 12 o'clock tick is longer and thicker so the face's
    # orientation reads instantly without needing explicit "12" text.
    for hour in range(12):
        angle = 2 * np.pi * hour / 12
        x_out = clock_radius * np.sin(angle)
        y_out = clock_radius * np.cos(angle)
        if hour == 0:
            inner = 0.78
            lw = 2.8
        else:
            inner = 0.88
            lw = 1.6
        x_in = inner * clock_radius * np.sin(angle)
        y_in = inner * clock_radius * np.cos(angle)
        ax.plot([x_out, x_in], [y_out, y_in], color='black', lw=lw)

    # Hand angles (matplotlib 0 = east, rotates counterclockwise; we want
    # 12 at top, clockwise).
    hours_angle = (3 - (current_time.hour % 12 + current_time.minute / 60)) * 2 * np.pi / 12
    minutes_angle = (15 - (current_time.minute + current_time.second / 60)) * 2 * np.pi / 60
    hours_angle = np.pi / 2 - hours_angle
    minutes_angle = np.pi / 2 - minutes_angle

    # Hour hand: short + thick. Minute hand: long + slightly thinner.
    # Round caps read cleaner at small sizes than the default butt caps.
    ax.plot([0, 0.50 * np.sin(hours_angle)], [0, 0.50 * np.cos(hours_angle)],
            color='black', lw=4, solid_capstyle='round')
    ax.plot([0, 0.85 * np.sin(minutes_angle)], [0, 0.85 * np.cos(minutes_angle)],
            color='black', lw=2.8, solid_capstyle='round')
    # Center hub.
    ax.plot(0, 0, marker='o', markersize=3, color='black')


def make_map(region=None,
        start_date=None,
        end_date=None,
        chip_dt=None,
        title=None,
        background='google',
        shared_dict=None,
        map_extent=None,
        zoom_level=None,
        glm_path=None,
        save=False,
        save_format=None,
        gpkg_path=None,
        use_polygons=False,
        output_file=None,
        fig_size=None,
        frame_dpi=None,
        isslis_flashes=None,
        show_grid=False,
        plot=False,
        **kwargs):

    fig_size = fig_size or DEFAULT_FIG_SIZE
    frame_dpi = frame_dpi or DEFAULT_FRAME_DPI

    crs = ccrs.PlateCarree()

    fig, ax = plt.subplots(figsize=fig_size, subplot_kw={'projection': crs}, dpi=frame_dpi)

    # Leave room for title above and timestamp below the map
    fig.subplots_adjust(left=0.0, right=1.0, bottom=0.06, top=0.93)

    ax.set_extent(map_extent, crs=crs)
    ax.axis('off')

    # Anchor the analog clock to the drawn-map's bottom-right corner.
    # Cartopy letterboxes the rendered map to preserve the AOI aspect
    # ratio, so the right edge of the axes (x=1.0) is NOT necessarily
    # the right edge of the visible map — for a square-ish AOI there's
    # a wide empty strip on either side. Compute where the map really
    # ends, then place the clock fully inside the lower-right corner.
    #
    # Axes dimensions are in figure-fraction coordinates but the figure
    # is 16:9, so fig-x and fig-y units are physically different. We
    # size the clock axes in INCHES then convert to fig fractions so
    # that (a) the allocated box is physically square before
    # set_aspect('equal', 'box') is applied (no implicit shrink), and
    # (b) the right and bottom paddings are the same physical distance
    # on screen rather than the same fig-fraction (which would give a
    # ~1.78x asymmetry on a 16:9 figure).
    _, map_b, map_r, _ = compute_drawn_map_bounds(
        fig_size, map_extent, axes_bbox=(0.0, 0.06, 1.0, 0.93))
    clock_diam_in = 0.72   # ~86 px at mp4 120 dpi, ~36 px at gif 50 dpi
    pad_in = 0.135         # ~same physical distance on all sides
    fig_w_in, fig_h_in = fig_size
    clock_w = clock_diam_in / fig_w_in
    clock_h = clock_diam_in / fig_h_in
    pad_w = pad_in / fig_w_in
    pad_h = pad_in / fig_h_in
    clock_ax = fig.add_axes([
        map_r - clock_w - pad_w,
        map_b + pad_h,
        clock_w,
        clock_h,
    ])
    clock_ax.set_aspect('equal', 'box')
    clock_ax.axis('off')

    # Add map background from pre-fetched image
    background_img = imread(io.BytesIO(shared_dict['background_image']), format='png')
    ax.imshow(background_img, origin='upper', extent=map_extent,
              transform=ccrs.PlateCarree(), interpolation='bilinear')

    if glm_path is None:
        pass  # No GLM layer — background only (ISS LIS-only mode)
    elif use_polygons:
        print(f"\nUsing polygons: {gpkg_path}")
        print(f"start_date: {start_date}, end_date: {end_date}")
        print(f"glm_path: {glm_path}")
        layer_name = f"{chip_dt.year}-{chip_dt.month}-{chip_dt.day}-{chip_dt.hour}"
        print(f"layer_name: {layer_name}")
        try:
            poly_gdf = gpd.read_file(gpkg_path, layer=layer_name)
            poly_gdf.plot(ax=ax, column='mean_TOE', alpha=0.5, edgecolor='k', transform=crs)
        except Exception as e:
            # Many layer_name values won't exist in the gpkg (frames between
            # storms have no polygons). That's expected, but we still want
            # the type and message visible so a real bug isn't masked by
            # the silent skip.
            print(f"polygon layer {layer_name} not rendered: {type(e).__name__}: {e}")
    else:
        # Load and render the GeoTIFF GLM chip
        with rasterio.open(glm_path) as src:
            if src.crs != 'EPSG:4326':
                transform_matrix, width, height = calculate_default_transform(
                    src.crs, 'EPSG:4326', src.width, src.height, *src.bounds)

                data = np.empty((height, width), dtype=rasterio.float32)

                reproject(
                    source=rasterio.band(src, 1),
                    destination=data,
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform_matrix,
                    dst_crs='EPSG:4326',
                    resampling=Resampling.nearest)

                extent = [transform_matrix[2], transform_matrix[2] + transform_matrix[0] * width,
                          transform_matrix[5] + transform_matrix[4] * height, transform_matrix[5]]
            else:
                data = src.read(1)
                extent = [src.bounds.left, src.bounds.right, src.bounds.bottom, src.bounds.top]

            masked_data = np.ma.masked_where(data == 0, data)
            ax.imshow(masked_data, origin='upper', extent=extent, transform=ccrs.PlateCarree(),
                      alpha=0.5, cmap='jet')

    # Overlay ISS LIS flash points (if available for this frame)
    if isslis_flashes is not None and len(isslis_flashes) > 0:
        ax.scatter(isslis_flashes['flash_longitude'].values,
                   isslis_flashes['flash_latitude'].values,
                   c='magenta', s=40, marker='*', alpha=0.9,
                   edgecolors='white', linewidths=0.5,
                   transform=ccrs.PlateCarree(), zorder=5,
                   label=f"ISS LIS ({len(isslis_flashes)})")
        ax.legend(loc='lower left', fontsize=8, framealpha=0.7)

    if show_grid:
        ax.gridlines()

    # Map title — above the map area (pre-built by movie_map.simplify_title)
    fig.text(0.5, 0.96, title, color='black', fontsize=16, fontweight='bold',
             ha='center', va='center')

    # Frame timestamp — below the map area (start_date is already formatted local time)
    fig.text(0.5, 0.02, start_date, color='black', fontsize=14, fontweight='bold',
             ha='center', va='center')

    # Clock uses UTC datetime (if provided), otherwise skip
    if chip_dt is not None:
        draw_clock(clock_ax, chip_dt)

    fig.savefig(output_file, dpi=frame_dpi, format=save_format)
    plt.close(fig)


def main(**kwargs):
    make_map(**kwargs)


def parse_opt():
    parser = argparse.ArgumentParser(description="Generate a single GLM animation frame")

    parser.add_argument('--region', type=str, default='tucson', help='which project/AOI')
    parser.add_argument('--background', type=str, choices=['osm', 'toner', 'watercolor',
                        'terrain-background', 'google', 'image', 'none'],
                        default='google', help='which map background to use')

    parser.add_argument('--start-date', help='start of datetime window')
    parser.add_argument('--end-date', help='end of datetime window')

    parser.add_argument('--save', action='store_true', help='save plot')
    parser.add_argument('--save-format', type=str, choices=['pdf', 'jpg'], default='pdf',
                        help='file format to save maps')
    parser.add_argument('--show-grid', action='store_true', help='draw grid lines')
    parser.add_argument('--plot', action='store_true', help='show plot on screen')
    return parser.parse_args()


if __name__ == "__main__":
    opt = parse_opt()
    main(**vars(opt))

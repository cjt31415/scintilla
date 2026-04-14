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


def draw_clock(ax, current_time):
    clock_radius = 1
    ax.set_xlim(-1.5, 1.5)
    ax.set_ylim(-1.5, 1.5)
    ax.set_aspect('equal', 'box')
    ax.axis('off')

    # Draw clock face
    circle = plt.Circle((0, 0), clock_radius, edgecolor='black', facecolor='white')
    ax.add_patch(circle)

    # Draw tick marks and labels
    for hour in range(12):
        angle = 2 * np.pi * hour / 12
        x_start = clock_radius * np.sin(angle)
        y_start = clock_radius * np.cos(angle)
        x_end = 0.9 * clock_radius * np.sin(angle)
        y_end = 0.9 * clock_radius * np.cos(angle)
        ax.plot([x_start, x_end], [y_start, y_end], color='black')

    # Label specific hours
    hour_labels = {0: "12", 3: "3", 6: "6", 9: "9"}
    for hour, label in hour_labels.items():
        angle = 2 * np.pi * hour / 12
        x = 1.1 * clock_radius * np.sin(angle)
        y = 1.1 * clock_radius * np.cos(angle)
        ax.text(x, y, label, horizontalalignment='center', verticalalignment='center')

    # Calculate angles for the hands
    hours_angle = (3 - (current_time.hour % 12 + current_time.minute / 60)) * 2 * np.pi / 12
    minutes_angle = (15 - (current_time.minute + current_time.second / 60)) * 2 * np.pi / 60

    # Correcting the angles by subtracting from pi/2 to realign
    hours_angle = np.pi/2 - hours_angle
    minutes_angle = np.pi/2 - minutes_angle

    # Draw hour and minute hands
    ax.plot([0, 0.5 * np.sin(hours_angle)], [0, 0.5 * np.cos(hours_angle)], color='black', lw=5)
    ax.plot([0, 0.8 * np.sin(minutes_angle)], [0, 0.8 * np.cos(minutes_angle)], color='black', lw=3)


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

    # Add secondary axis for the clock
    clock_ax = fig.add_axes([0.88, 0.12, 0.10, 0.10])
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

#!/usr/bin/env python
"""
    map_utils.py - map background tile providers and geospatial display utilities
    for GLM lightning animation and related cartopy-based visualizations.
"""
import math
import os

import cartopy.io.img_tiles as cimgt

STADIA_API_TOKEN = os.environ.get("STADIA_API_TOKEN", "")


class CustomTileSource(cimgt.GoogleTiles):
    """Stadia Maps tile source for Stamen-style map backgrounds."""

    def __init__(self, map_name, api_token, high_res=False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_token = api_token
        self.high_res = high_res
        self.map_name = map_name
        self.url = None

        if map_name == 'toner':
            self.url = "https://tiles.stadiamaps.com/tiles/stamen_toner/{z}/{x}/{y}{r}.png"
        elif map_name == 'watercolor':
            self.url = "https://tiles.stadiamaps.com/tiles/stamen_watercolor/{z}/{x}/{y}.jpg"
        elif map_name == 'terrain-background':
            self.url = "https://tiles.stadiamaps.com/tiles/stamen_terrain/{z}/{x}/{y}{r}.jpg"
        else:
            raise ValueError("Unsupported map_name in CustomTileSource")

    def _image_url(self, tile):
        x, y, z = tile
        resolution = "@2x" if self.high_res else ""
        url_with_coords = self.url.format(z=z, x=x, y=y, r=resolution)
        url = f"{url_with_coords}?api_key={self.api_token}"
        return url


def map_background(map_name):
    """Return a cartopy tile source for the given map background name."""
    if map_name == 'google':
        return cimgt.GoogleTiles()
    elif map_name == 'osm':
        return cimgt.OSM()
    elif map_name == 'image':
        return cimgt.QuadtreeTiles()
    elif map_name == 'none':
        return None
    else:
        return CustomTileSource(map_name=map_name, api_token=STADIA_API_TOKEN, high_res=False)


def degrees_to_meters(latitude, delta_lat_deg, delta_lon_deg):
    """Convert degree deltas to meters at a given latitude."""
    earth_circumference = 40_075_000  # meters
    meters_per_degree_latitude = earth_circumference / 360

    meters_lat = delta_lat_deg * meters_per_degree_latitude

    meters_per_degree_longitude = meters_per_degree_latitude * math.cos(math.radians(latitude))
    meters_lon = delta_lon_deg * meters_per_degree_longitude

    return meters_lat, meters_lon

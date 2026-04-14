#!/usr/bin/env python
"""
    aoi_to_16-9.py - read an AOI geojson, adjust the bounding box to 16:9 aspect ratio, save

    Usage:
        ./aoi_to_16-9.py --aoi tucson-area
        ./aoi_to_16-9.py --aoi tucson-area --output-name tucson-area-wide --mode horizontal
"""

import argparse
import json

from scintilla.common.defines import AOI_DIR
from scintilla.common.utils import aoi_list
from scintilla.tools.aoi_tool import snap_to_169


def adjust_polygon_aspect_ratio(polygon, mode=None):
    """Return a closed 16:9 ring of (lon, lat) pairs derived from `polygon`.

    Thin wrapper around aoi_tool.snap_to_169: extracts the polygon's bbox,
    delegates the math, and converts the resulting bbox back to a closed
    GeoJSON ring.
    """
    coordinates = polygon['coordinates'][0]
    min_x = min(p[0] for p in coordinates)
    max_x = max(p[0] for p in coordinates)
    min_y = min(p[1] for p in coordinates)
    max_y = max(p[1] for p in coordinates)

    current_aspect_ratio = (max_x - min_x) / (max_y - min_y)
    print(f"  Current aspect ratio: {current_aspect_ratio:.2f}, adjusting {mode or 'auto'}")

    west, east, south, north = snap_to_169(min_x, max_x, min_y, max_y, mode=mode)
    return [[west, south], [east, south], [east, north], [west, north], [west, south]]


def main(aoi=None, output_name=None, mode=None):
    input_path = AOI_DIR / f"{aoi}_aoi.geojson"
    output_name = output_name or f"{aoi}_169"
    output_path = AOI_DIR / f"{output_name}_aoi.geojson"

    with open(input_path) as f:
        geojson = json.load(f)

    for feature in geojson['features']:
        if feature['geometry']['type'] == 'Polygon':
            feature['geometry']['coordinates'][0] = adjust_polygon_aspect_ratio(feature['geometry'], mode)

    with open(output_path, 'w') as f:
        json.dump(geojson, f, indent=2)

    print(f"{input_path} → {output_path}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Adjust an AOI bounding box polygon to 16:9 aspect ratio.')
    parser.add_argument('--aoi', type=str, required=True, choices=aoi_list(),
                        help='name of AOI')
    parser.add_argument('--output-name', type=str,
                        help='output AOI name (default: <aoi>_169)')
    parser.add_argument('--mode', choices=['horizontal', 'vertical'],
                        help='direction to expand (auto-detected if omitted)')

    args = parser.parse_args()
    main(args.aoi, args.output_name, args.mode)

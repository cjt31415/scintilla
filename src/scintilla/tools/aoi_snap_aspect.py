#!/usr/bin/env python
"""
    aoi_snap_aspect.py - read an AOI geojson, snap its bbox to a target
    aspect ratio (16:9 by default), save under a new name.

    Usage:
        ./aoi_snap_aspect.py --aoi tucson-area                       # 16:9 (default)
        ./aoi_snap_aspect.py --aoi tucson-area --aspect 1:1          # square
        ./aoi_snap_aspect.py --aoi tucson-area --aspect 4:3
        ./aoi_snap_aspect.py --aoi tucson-area --aspect 9:16 --mode vertical
        ./aoi_snap_aspect.py --aoi tucson-area --output-name tucson-square

    Default output name suffix:
        --aspect 16:9  → <aoi>_169   (preserves the legacy convention)
        --aspect 1:1   → <aoi>_1x1
        --aspect 4:3   → <aoi>_4x3
        --aspect W:H   → <aoi>_WxH
"""

import argparse
import json

from scintilla.common.defines import AOI_DIR
from scintilla.common.utils import aoi_list
from scintilla.tools.aoi_tool import parse_aspect, snap_to_aspect


def default_suffix(aspect_str):
    """Default output-name suffix derived from the aspect string.

    16:9 stays as '_169' (legacy convention); others become '_WxH'.
    """
    if aspect_str == '16:9':
        return '_169'
    w, h = aspect_str.split(':')
    return f'_{w}x{h}'


def adjust_polygon_aspect_ratio(polygon, target_aspect, mode=None):
    """Return a closed ring of (lon, lat) pairs snapped to target_aspect.

    Thin wrapper around aoi_tool.snap_to_aspect: extracts the polygon's bbox,
    delegates the math, and converts the resulting bbox back to a closed
    GeoJSON ring.
    """
    coordinates = polygon['coordinates'][0]
    min_x = min(p[0] for p in coordinates)
    max_x = max(p[0] for p in coordinates)
    min_y = min(p[1] for p in coordinates)
    max_y = max(p[1] for p in coordinates)

    current_aspect = (max_x - min_x) / (max_y - min_y)
    print(f"  Current aspect: {current_aspect:.3f}, target: {target_aspect:.3f}, "
          f"mode: {mode or 'auto'}")

    west, east, south, north = snap_to_aspect(min_x, max_x, min_y, max_y,
                                              target_aspect, mode=mode)
    return [[west, south], [east, south], [east, north], [west, north], [west, south]]


def main(aoi=None, output_name=None, mode=None, aspect='16:9'):
    target_aspect = parse_aspect(aspect)
    input_path = AOI_DIR / f"{aoi}_aoi.geojson"
    output_name = output_name or f"{aoi}{default_suffix(aspect)}"
    output_path = AOI_DIR / f"{output_name}_aoi.geojson"

    with open(input_path) as f:
        geojson = json.load(f)

    for feature in geojson['features']:
        if feature['geometry']['type'] == 'Polygon':
            feature['geometry']['coordinates'][0] = adjust_polygon_aspect_ratio(
                feature['geometry'], target_aspect, mode=mode)

    with open(output_path, 'w') as f:
        json.dump(geojson, f, indent=2)

    print(f"{input_path} → {output_path}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Snap an AOI bounding box polygon to a target aspect ratio.')
    parser.add_argument('--aoi', type=str, required=True, choices=aoi_list(),
                        help='name of AOI')
    parser.add_argument('--aspect', type=str, default='16:9', metavar='W:H',
                        help='target aspect ratio as W:H (default: 16:9). '
                             'Examples: 16:9, 1:1, 4:3, 9:16, 21:9.')
    parser.add_argument('--output-name', type=str,
                        help='output AOI name (default: <aoi>_169 for 16:9, '
                             '<aoi>_WxH otherwise)')
    parser.add_argument('--mode', choices=['horizontal', 'vertical'],
                        help='direction to expand (auto-detected if omitted)')

    args = parser.parse_args()
    main(args.aoi, args.output_name, args.mode, args.aspect)

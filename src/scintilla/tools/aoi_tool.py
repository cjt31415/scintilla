#!/usr/bin/env python
"""
    aoi_tool.py - interactive AOI viewer, creator, and editor

    Uses folium/Leaflet for interactive slippy maps in the browser.
    A tiny localhost HTTP server captures the drawn rectangle coordinates.

    View mode:   Show AOIs on an interactive map
    Create mode: Draw a new AOI rectangle, save as GeoJSON
    Edit mode:   Load an existing AOI, redraw, save

    Usage:
        ./aoi_tool.py                                       # view all AOIs
        ./aoi_tool.py --filter tucson                       # view tucson-related AOIs
        ./aoi_tool.py --create                              # create new AOI
        ./aoi_tool.py --create --near arizona               # create, start near Arizona
        ./aoi_tool.py --create --snap-aspect 16:9           # create with 16:9 snap
        ./aoi_tool.py --create --snap-aspect 1:1            # create with square snap
        ./aoi_tool.py --edit tucson-area                    # edit existing AOI
        ./aoi_tool.py --edit tucson-area --snap-aspect 4:3  # edit + snap to 4:3
"""

import argparse
import json
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import folium
from folium.plugins import Draw

from scintilla.common.defines import AOI_DIR
from scintilla.common.utils import aoi_area_in_km2, aoi_list, load_geometry

SERVER_PORT = 18923
EXCHANGE_DIR = Path(tempfile.gettempdir()) / "aoi_tool"


def get_aoi_bounds(name):
    """Get [[south, west], [north, east]] for folium fit_bounds."""
    gdf = load_geometry(name)
    minx, miny, maxx, maxy = gdf.total_bounds
    return [[miny, minx], [maxy, maxx]]


def parse_aspect(s):
    """Parse a 'W:H' string into a float (width/height).

    Examples: '16:9' → 1.778, '1:1' → 1.0, '4:3' → 1.333, '9:16' → 0.5625.
    """
    w, h = s.split(':')
    return float(w) / float(h)


def snap_to_aspect(west, east, south, north, target_aspect, mode=None):
    """Adjust a bounding box to the target aspect ratio, expanding as needed.

    `target_aspect` is width/height (e.g., 16/9 ≈ 1.778, 1.0 for square).
    `mode` controls which axis to expand:
        'horizontal' — widen east-west
        'vertical'   — extend north-south
        None         — auto-detect (widen the dimension that's too narrow)
    """
    width = east - west
    height = north - south

    if mode is None:
        mode = 'horizontal' if (width / height) < target_aspect else 'vertical'

    if mode == 'horizontal':
        new_width = height * target_aspect
        delta = (new_width - width) / 2
        west -= delta
        east += delta
    else:
        new_height = width / target_aspect
        delta = (new_height - height) / 2
        south -= delta
        north += delta

    return west, east, south, north


def save_aoi_geojson(name, west, east, south, north):
    """Save an AOI as a GeoJSON FeatureCollection."""
    geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [west, south], [east, south],
                    [east, north], [west, north],
                    [west, south],
                ]]
            }
        }]
    }

    out_path = AOI_DIR / f"{name}_aoi.geojson"
    with open(out_path, 'w') as f:
        json.dump(geojson, f, indent=2)
    return out_path


def add_aois_to_map(m, aoi_names, edit_name=None):
    """Draw AOI rectangles with labels on a folium map."""
    for name in aoi_names:
        bounds = get_aoi_bounds(name)
        sw, ne = bounds[0], bounds[1]

        color = '#ff4444' if name == edit_name else 'blue'
        weight = 3 if name == edit_name else 1.5
        fill_opacity = 0.15 if name == edit_name else 0.08

        gdf = load_geometry(name)
        area = aoi_area_in_km2(gdf)

        folium.Rectangle(
            bounds=bounds, color=color, weight=weight,
            fill=True, fill_color=color, fill_opacity=fill_opacity,
            popup=folium.Popup(f"<b>{name}</b><br>{area:,.0f} km²", max_width=200),
            tooltip=name,
        ).add_to(m)

        # Label
        lat_c = (sw[0] + ne[0]) / 2
        lon_c = (sw[1] + ne[1]) / 2
        folium.Marker(
            location=[lat_c, lon_c],
            icon=folium.DivIcon(
                html=f'<div style="font-size:10px;font-weight:bold;color:#333;'
                     f'background:rgba(255,255,255,0.7);padding:1px 4px;'
                     f'border-radius:3px;white-space:nowrap">{name}</div>',
                icon_size=(0, 0), icon_anchor=(0, 0),
            ),
        ).add_to(m)


def fit_to_aois(m, aoi_names, focus_name=None):
    """Fit the map bounds to show the given AOIs."""
    if focus_name:
        bounds = get_aoi_bounds(focus_name)
        sw, ne = bounds[0], bounds[1]
        dlat = (ne[0] - sw[0]) * 0.3
        dlon = (ne[1] - sw[1]) * 0.3
        m.fit_bounds([[sw[0] - dlat, sw[1] - dlon], [ne[0] + dlat, ne[1] + dlon]])
    elif aoi_names:
        all_bounds = [get_aoi_bounds(n) for n in aoi_names]
        sw = [min(b[0][0] for b in all_bounds), min(b[0][1] for b in all_bounds)]
        ne = [max(b[1][0] for b in all_bounds), max(b[1][1] for b in all_bounds)]
        m.fit_bounds([sw, ne], padding=[20, 20])


def build_interactive_map(aoi_names, edit_name=None, near_name=None, snap_aspect_str=None):
    """Build a folium map with drawing tools that POST the selection to localhost."""
    m = folium.Map(location=[34.0, -111.0], zoom_start=5,
                   tiles='CartoDB positron', control_scale=True)

    add_aois_to_map(m, aoi_names, edit_name=edit_name)
    fit_to_aois(m, aoi_names, focus_name=edit_name or near_name)

    # Drawing tools — rectangle only
    Draw(
        draw_options={
            'rectangle': {'shapeOptions': {'color': '#ff0000', 'weight': 2, 'fillOpacity': 0.1}},
            'polyline': False, 'polygon': False,
            'circle': False, 'circlemarker': False, 'marker': False,
        },
        edit_options={'edit': False, 'remove': True},
    ).add_to(m)

    # JavaScript: on draw, POST coordinates to localhost, show confirmation
    map_var = m.get_name()  # already includes 'map_' prefix
    if snap_aspect_str:
        snap_target_js = repr(parse_aspect(snap_aspect_str))
        snap_label = snap_aspect_str
    else:
        snap_target_js = 'null'
        snap_label = ''
    js = f"""
    <script>
    document.addEventListener('DOMContentLoaded', function() {{
        setTimeout(function() {{
            var map = {map_var};

            map.on('draw:created', function(e) {{
                var bounds = e.layer.getBounds();
                var south = bounds.getSouth(), north = bounds.getNorth();
                var west = bounds.getWest(), east = bounds.getEast();

                var snapTarget = {snap_target_js};
                if (snapTarget !== null) {{
                    var width = east - west, height = north - south;
                    var ratio = width / height;
                    if (ratio < snapTarget) {{
                        var d = (height * snapTarget - width) / 2;
                        west -= d; east += d;
                    }} else {{
                        var d = (width / snapTarget - height) / 2;
                        south -= d; north += d;
                    }}
                    L.rectangle([[south, west], [north, east]], {{
                        color: 'green', weight: 2, dashArray: '5,5', fill: false
                    }}).addTo(map).bindPopup('{snap_label} snapped');
                }}

                var data = {{west: west, east: east, south: south, north: north}};
                var area = Math.abs((east-west)*(north-south)) * 111*111 *
                           Math.cos(((south+north)/2) * Math.PI/180);

                e.layer.bindPopup(
                    '<b>Selection</b><br>' +
                    'W: ' + west.toFixed(4) + ', E: ' + east.toFixed(4) + '<br>' +
                    'S: ' + south.toFixed(4) + ', N: ' + north.toFixed(4) + '<br>' +
                    'Ratio: ' + ((east-west)/(north-south)).toFixed(2) + '<br>' +
                    'Area: ~' + Math.round(area).toLocaleString() + ' km²<br><br>' +
                    '<em>Sending to terminal...</em>'
                ).openPopup();

                // POST to same origin (no CORS issues)
                fetch('/aoi', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify(data)
                }}).then(function(r) {{
                    e.layer.setPopupContent(
                        e.layer.getPopup().getContent().replace(
                            'Sending to terminal...', '✓ Received by terminal')
                    );
                }}).catch(function(err) {{
                    e.layer.setPopupContent(
                        e.layer.getPopup().getContent().replace(
                            'Sending to terminal...', '✗ Could not reach terminal')
                    );
                }});
            }});
        }}, 500);
    }});
    </script>
    """
    m.get_root().html.add_child(folium.Element(js))
    return m


class SelectionHandler(BaseHTTPRequestHandler):
    """HTTP handler that serves the map HTML and captures the AOI selection."""

    selection = None
    html_content = b""

    def do_GET(self):
        """Serve the map HTML."""
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(SelectionHandler.html_content)

    def do_POST(self):
        """Receive the drawn rectangle coordinates."""
        length = int(self.headers['Content-Length'])
        body = self.rfile.read(length)
        SelectionHandler.selection = json.loads(body)
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"status": "ok"}')

    def log_message(self, format, *args):
        print(f"  [server] {self.command} {self.path}")


def view_mode(aoi_names):
    """Show AOIs on an interactive map in the browser."""
    EXCHANGE_DIR.mkdir(exist_ok=True)
    m = folium.Map(location=[34.0, -111.0], zoom_start=5,
                   tiles='CartoDB positron', control_scale=True)
    add_aois_to_map(m, aoi_names)
    fit_to_aois(m, aoi_names)

    # Use unique filename to avoid browser cache
    import time
    html_path = EXCHANGE_DIR / f"aoi_view_{int(time.time())}.html"
    m.save(str(html_path))
    print(f"Opening map with {len(aoi_names)} AOIs...")
    subprocess.run(['open', str(html_path)])


def interactive_mode(edit_name, near_name, snap_aspect_str, filter_terms=None):
    """Create or edit an AOI interactively."""
    EXCHANGE_DIR.mkdir(exist_ok=True)
    all_names = aoi_list()

    if filter_terms:
        show_names = [n for n in all_names
                      if any(f.lower() in n.lower() for f in filter_terms)]
    else:
        show_names = all_names

    # Always include the edit target
    if edit_name and edit_name not in show_names:
        show_names.append(edit_name)

    m = build_interactive_map(show_names, edit_name=edit_name,
                               near_name=near_name, snap_aspect_str=snap_aspect_str)

    # Save to temp file first (ensures all Elements are included),
    # then read back the HTML to serve from localhost
    EXCHANGE_DIR.mkdir(exist_ok=True)
    tmp_path = EXCHANGE_DIR / "aoi_create.html"
    m.save(str(tmp_path))
    html_content = tmp_path.read_text()

    mode_str = f"Edit: {edit_name}" if edit_name else "Create new AOI"
    snap_str = f" [{snap_aspect_str} snap]" if snap_aspect_str else ""

    print(f"\n{'='*55}")
    print(f"  {mode_str}{snap_str}")
    print("  Draw a rectangle on the map.")
    print("  Coordinates are sent here automatically.")
    print(f"{'='*55}")

    # Start HTTP server that serves the map AND receives the selection
    SelectionHandler.html_content = html_content.encode('utf-8')
    SelectionHandler.selection = None
    server = HTTPServer(('localhost', SERVER_PORT), SelectionHandler)

    # Serve requests until we get a POST with the selection
    def serve_until_selection():
        while SelectionHandler.selection is None:
            server.handle_request()

    server_thread = threading.Thread(target=serve_until_selection, daemon=True)
    server_thread.start()

    # Open browser pointing to localhost
    subprocess.run(['open', f'http://localhost:{SERVER_PORT}'])

    # Wait for the browser to POST the selection
    print("\n  Waiting for rectangle selection in browser...")
    server_thread.join(timeout=300)
    server.server_close()

    data = SelectionHandler.selection
    SelectionHandler.selection = None  # Reset for next use

    if not data:
        print("  No selection received (timed out or cancelled).")
        return

    west, east = data['west'], data['east']
    south, north = data['south'], data['north']

    # Apply snap on Python side too
    if snap_aspect_str:
        target_aspect = parse_aspect(snap_aspect_str)
        west, east, south, north = snap_to_aspect(west, east, south, north, target_aspect)

    # Calculate area
    geom_json = {
        'type': 'Polygon',
        'coordinates': [[[west, south], [east, south], [east, north], [west, north], [west, south]]]
    }
    area = aoi_area_in_km2(geom_json)
    ratio = (east - west) / (north - south)

    print(f"\n  Bounds: [{west:.4f}, {south:.4f}] to [{east:.4f}, {north:.4f}]")
    print(f"  Aspect ratio: {ratio:.2f}")
    print(f"  Area: {area:,.0f} km²")

    if edit_name:
        old_area = aoi_area_in_km2(load_geometry(edit_name))
        print(f"  (was {old_area:,.0f} km²)")
        name = input(f"\n  Save as '{edit_name}' (enter for same, or new name): ").strip()
        if not name:
            name = edit_name
    else:
        name = input("\n  AOI name: ").strip()

    if name:
        out_path = save_aoi_geojson(name, west, east, south, north)
        print(f"  Saved: {out_path}")
    else:
        print("  No name entered, not saved.")


def parse_opt():
    parser = argparse.ArgumentParser(
        description="Interactive AOI viewer, creator, and editor")

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument('--create', action='store_true',
                            help='create a new AOI interactively')
    mode_group.add_argument('--edit', type=str, metavar='AOI',
                            help='edit an existing AOI')

    parser.add_argument('--filter', type=str, nargs='+',
                        help='filter which AOIs are shown (all modes)')
    parser.add_argument('--near', type=str, metavar='AOI',
                        help='center initial view near this AOI (create mode)')
    parser.add_argument('--snap-aspect', type=str, default=None, metavar='W:H',
                        help='snap the AOI to a target aspect ratio (e.g., 16:9, 1:1, 4:3, 9:16)')

    return parser.parse_args()


def main():
    opt = parse_opt()

    if opt.create or opt.edit:
        interactive_mode(edit_name=opt.edit, near_name=opt.near,
                         snap_aspect_str=opt.snap_aspect, filter_terms=opt.filter)
    else:
        names = aoi_list()
        if opt.filter:
            names = [n for n in names
                     if any(f.lower() in n.lower() for f in opt.filter)]
            if not names:
                print(f"No AOIs matching filter: {opt.filter}")
                return
        view_mode(names)


if __name__ == "__main__":
    main()

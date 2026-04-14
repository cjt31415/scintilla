#!/usr/bin/env python
"""
    plot_glm_coverage.py - generate a static figure showing GLM-16 and
    GLM-18 satellite zenith-angle coverage contours over an AOI, with
    ISS LIS ground tracks overlaid.

    Output: SVG + PNG written to docs/img/<output_stem>.{svg,png}.

    Default invocation produces the 2023-06-04 Manitoba figure used in
    docs/glm_sensor_coverage.md. The core plotting function takes AOI
    bbox and ISS pass endpoints as parameters so it can be re-run for
    any other AOI + date combination.
"""

import argparse
from pathlib import Path

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

# -----------------------------------------------------------------------------
# Physical constants
# -----------------------------------------------------------------------------
Re = 6378.14   # km, Earth equatorial radius
Rg = 42164.17  # km, geostationary orbit radius (from Earth center)


def geocentric_angle_for_zenith(zenith_deg: float) -> float:
    """Return the geocentric angle (degrees) at which a ground point
    sees a geostationary satellite at the given satellite-zenith angle.

    Derivation: in the triangle Earth-center / satellite / ground-point,
    cos(beta) = (sin^2(zeta) * Re + cos(zeta) * sqrt(Rg^2 - Re^2 * sin^2(zeta))) / Rg

    At zenith=0 this returns 0 (sub-satellite point). At zenith=90 it
    returns the horizon-limited ~81.3 degrees.
    """
    zeta = np.radians(zenith_deg)
    sin2_zeta = np.sin(zeta) ** 2
    cos_zeta = np.cos(zeta)
    discriminant = Rg ** 2 - Re ** 2 * sin2_zeta
    cos_beta = (sin2_zeta * Re + cos_zeta * np.sqrt(discriminant)) / Rg
    cos_beta = np.clip(cos_beta, -1.0, 1.0)
    return float(np.degrees(np.arccos(cos_beta)))


def small_circle_points(center_lon: float, center_lat: float,
                        radius_deg: float, n: int = 361) -> tuple:
    """Parametric points on a small circle of given angular radius (degrees)
    around (center_lon, center_lat) on a sphere. Returns (lons, lats) arrays."""
    clat = np.radians(center_lat)
    clon = np.radians(center_lon)
    r = np.radians(radius_deg)
    phi = np.linspace(0, 2 * np.pi, n)

    sin_lat = np.sin(clat) * np.cos(r) + np.cos(clat) * np.sin(r) * np.cos(phi)
    lats = np.arcsin(np.clip(sin_lat, -1.0, 1.0))
    y = np.sin(phi) * np.sin(r) * np.cos(clat)
    x = np.cos(r) - np.sin(clat) * np.sin(lats)
    lons = clon + np.arctan2(y, x)

    return np.degrees(lons), np.degrees(lats)


def great_circle_interp(lon1: float, lat1: float,
                        lon2: float, lat2: float,
                        n: int = 60) -> tuple:
    """Interpolate n points along the great circle between two points."""
    lat1_r, lon1_r = np.radians(lat1), np.radians(lon1)
    lat2_r, lon2_r = np.radians(lat2), np.radians(lon2)

    cos_d = (
        np.sin(lat1_r) * np.sin(lat2_r)
        + np.cos(lat1_r) * np.cos(lat2_r) * np.cos(lon2_r - lon1_r)
    )
    d = np.arccos(np.clip(cos_d, -1.0, 1.0))
    if d < 1e-9:
        return np.array([lon1, lon2]), np.array([lat1, lat2])

    fracs = np.linspace(0, 1, n)
    sin_d = np.sin(d)
    A = np.sin((1 - fracs) * d) / sin_d
    B = np.sin(fracs * d) / sin_d
    x = A * np.cos(lat1_r) * np.cos(lon1_r) + B * np.cos(lat2_r) * np.cos(lon2_r)
    y = A * np.cos(lat1_r) * np.sin(lon1_r) + B * np.cos(lat2_r) * np.sin(lon2_r)
    z = A * np.sin(lat1_r) + B * np.sin(lat2_r)
    lats = np.degrees(np.arctan2(z, np.sqrt(x ** 2 + y ** 2)))
    lons = np.degrees(np.arctan2(y, x))
    return lons, lats


def great_circle_extend(lon1: float, lat1: float,
                        lon2: float, lat2: float,
                        ext_start_deg: float, ext_end_deg: float,
                        n: int = 120) -> tuple:
    """Great-circle track between two points, extended by ext_start_deg
    beyond the start and ext_end_deg beyond the end. Extension is along
    the same great circle (backward/forward from the original endpoints),
    not linear in lat/lon.
    """
    # Compute forward azimuth at p2 and backward azimuth at p1 via spherical
    # trig, then use them to walk along the great circle for the extension.
    lat1_r, lon1_r = np.radians(lat1), np.radians(lon1)
    lat2_r, lon2_r = np.radians(lat2), np.radians(lon2)

    # Bearing from p1 toward p2 (forward azimuth at p1)
    dlon = lon2_r - lon1_r
    y = np.sin(dlon) * np.cos(lat2_r)
    x = np.cos(lat1_r) * np.sin(lat2_r) - np.sin(lat1_r) * np.cos(lat2_r) * np.cos(dlon)
    az_at_p1 = np.arctan2(y, x)  # bearing at p1 pointing toward p2
    # Bearing at p1 pointing AWAY from p2 (for extending before p1)
    az_away_p1 = az_at_p1 + np.pi

    # Bearing at p2 toward p1 (so "forward" means continuing past p2)
    dlon_rev = lon1_r - lon2_r
    y2 = np.sin(dlon_rev) * np.cos(lat1_r)
    x2 = np.cos(lat2_r) * np.sin(lat1_r) - np.sin(lat2_r) * np.cos(lat1_r) * np.cos(dlon_rev)
    az_at_p2_back = np.arctan2(y2, x2)
    # Bearing at p2 continuing past p2 (away from p1)
    az_fwd_p2 = az_at_p2_back + np.pi

    def walk(lat_r, lon_r, bearing_r, arc_deg):
        """Walk arc_deg degrees along the great circle from (lat, lon)
        at the given bearing. Returns (lat, lon) in radians."""
        arc = np.radians(arc_deg)
        lat_new = np.arcsin(
            np.sin(lat_r) * np.cos(arc) + np.cos(lat_r) * np.sin(arc) * np.cos(bearing_r)
        )
        lon_new = lon_r + np.arctan2(
            np.sin(bearing_r) * np.sin(arc) * np.cos(lat_r),
            np.cos(arc) - np.sin(lat_r) * np.sin(lat_new),
        )
        return lat_new, lon_new

    # Extended start
    if ext_start_deg > 0:
        lat_start_r, lon_start_r = walk(lat1_r, lon1_r, az_away_p1, ext_start_deg)
    else:
        lat_start_r, lon_start_r = lat1_r, lon1_r

    # Extended end
    if ext_end_deg > 0:
        lat_end_r, lon_end_r = walk(lat2_r, lon2_r, az_fwd_p2, ext_end_deg)
    else:
        lat_end_r, lon_end_r = lat2_r, lon2_r

    return great_circle_interp(
        np.degrees(lon_start_r), np.degrees(lat_start_r),
        np.degrees(lon_end_r), np.degrees(lat_end_r),
        n=n,
    )


# -----------------------------------------------------------------------------
# Main plotting function
# -----------------------------------------------------------------------------
def plot_glm_coverage(
    aoi_bbox: tuple,
    aoi_label: str,
    iss_passes: list,
    output_stem: str,
    output_dir: Path = None,
    title: str = None,
) -> tuple:
    """Produce the GLM-16 + GLM-18 coverage figure with ISS LIS tracks.

    Parameters
    ----------
    aoi_bbox : (west, south, east, north) in degrees
    aoi_label : string to label the AOI rectangle
    iss_passes : list of dicts with keys 'p1', 'p2', 'ext_start', 'ext_end',
                 'label', 'time', 'color', 'linestyle'
                 (p1/p2 as (lon, lat) tuples, in the order the ISS traveled)
    output_stem : filename stem (without extension) for the output files
    output_dir : directory to write to. Defaults to <repo>/docs/img/
    title : figure title. Auto-generated if None.

    Returns
    -------
    (png_path, svg_path) — paths to the two output files
    """
    # Projection: PlateCarree with an explicit extent. The rings get slight
    # visual distortion at high latitudes but the AOI + tracks are rendered
    # faithfully and meridian crossings are handled by ccrs.Geodetic().
    proj = ccrs.PlateCarree()
    fig = plt.figure(figsize=(12, 8))
    ax = fig.add_subplot(1, 1, 1, projection=proj)

    # Extent: show both sub-satellite points, the AOI, and the near-polar
    # Canadian coast. Wide enough to see GLM-18 at -137 and GLM-16 at -75.
    ax.set_extent([-160, -55, -5, 65], crs=ccrs.PlateCarree())

    # Map features
    ax.add_feature(cfeature.LAND, facecolor='#f2f2ef', edgecolor='#b0b0b0', linewidth=0.3)
    ax.add_feature(cfeature.OCEAN, facecolor='#ffffff')
    ax.add_feature(cfeature.COASTLINE, edgecolor='#808080', linewidth=0.3)
    ax.add_feature(cfeature.BORDERS, edgecolor='#b0b0b0', linewidth=0.3)
    gl = ax.gridlines(
        draw_labels=True, xlocs=range(-180, 181, 20), ylocs=range(-90, 91, 15),
        color='#d0d0d0', linewidth=0.3, alpha=0.6,
    )
    gl.top_labels = False
    gl.right_labels = False
    gl.xlabel_style = {'size': 8, 'color': '#555555'}
    gl.ylabel_style = {'size': 8, 'color': '#555555'}

    # -------------------------------------------------------------------------
    # GLM satellite coverage rings (zenith-angle thresholds from
    # docs/glm_sensor_coverage.md: <55 good, 55-65 marginal, 65-70 degraded,
    # >70 very poor)
    # -------------------------------------------------------------------------
    satellites = [
        {"name": "GOES-18", "lon": -137.2, "edge": "#0F6E56", "fill": "#5DCAA5"},
        {"name": "GOES-16", "lon": -75.2, "edge": "#185FA5", "fill": "#85B7EB"},
    ]
    zenith_rings = [
        {"zenith": 55, "width": 1.8, "style": "-",          "alpha": 0.9, "fill_alpha": 0.08},
        {"zenith": 65, "width": 1.4, "style": (0, (6, 3)),  "alpha": 0.75, "fill_alpha": 0.0},
        {"zenith": 70, "width": 1.0, "style": (0, (2, 3)),  "alpha": 0.55, "fill_alpha": 0.0},
    ]

    for sat in satellites:
        # Fill the "good detection" region (<55 zenith) as a tinted hint
        beta55 = geocentric_angle_for_zenith(55)
        lons55, lats55 = small_circle_points(sat["lon"], 0, beta55)
        ax.fill(lons55, lats55, color=sat["fill"], alpha=zenith_rings[0]["fill_alpha"],
                transform=ccrs.Geodetic(), zorder=1)

        # Draw each ring outline
        for ring in zenith_rings:
            beta = geocentric_angle_for_zenith(ring["zenith"])
            lons, lats = small_circle_points(sat["lon"], 0, beta)
            ax.plot(lons, lats, color=sat["edge"], linewidth=ring["width"],
                    linestyle=ring["style"], alpha=ring["alpha"],
                    transform=ccrs.Geodetic(), zorder=2)

        # Sub-satellite point marker (cross + label)
        ax.plot(sat["lon"], 0, marker='x', color=sat["edge"], markersize=10,
                markeredgewidth=2.5, transform=ccrs.PlateCarree(), zorder=5)
        ax.annotate(
            sat["name"], xy=(sat["lon"], 0), xytext=(0, -16),
            textcoords='offset points', ha='center', va='top',
            color=sat["edge"], fontsize=10, fontweight='bold',
            xycoords=ccrs.PlateCarree()._as_mpl_transform(ax),
            zorder=5,
        )
        ax.annotate(
            f"{abs(sat['lon']):.1f}°W", xy=(sat["lon"], 0), xytext=(0, -29),
            textcoords='offset points', ha='center', va='top',
            color=sat["edge"], fontsize=8,
            xycoords=ccrs.PlateCarree()._as_mpl_transform(ax),
            zorder=5,
        )

    # -------------------------------------------------------------------------
    # AOI rectangle
    # -------------------------------------------------------------------------
    aoi_west, aoi_south, aoi_east, aoi_north = aoi_bbox
    aoi_lons = [aoi_west, aoi_east, aoi_east, aoi_west, aoi_west]
    aoi_lats = [aoi_south, aoi_south, aoi_north, aoi_north, aoi_south]
    ax.fill(aoi_lons, aoi_lats, color='#E24B4A', alpha=0.15,
            transform=ccrs.Geodetic(), zorder=3)
    ax.plot(aoi_lons, aoi_lats, color='#C8322F', linewidth=2.0,
            transform=ccrs.Geodetic(), zorder=4)

    # AOI label at center
    ax.annotate(
        aoi_label,
        xy=((aoi_west + aoi_east) / 2, (aoi_south + aoi_north) / 2),
        xycoords=ccrs.PlateCarree()._as_mpl_transform(ax),
        color='#8A2220', fontsize=10, fontweight='bold',
        ha='center', va='center', zorder=5,
    )

    # NE corner callout
    ne_lon, ne_lat = aoi_east, aoi_north
    ax.plot(ne_lon, ne_lat, marker='o', color='#C8322F', markersize=7,
            markeredgewidth=1.5, markeredgecolor='white',
            transform=ccrs.PlateCarree(), zorder=6)
    ax.annotate(
        f"NE corner\n({ne_lat:.1f}°N, {abs(ne_lon):.0f}°W)",
        xy=(ne_lon, ne_lat), xytext=(10, 8), textcoords='offset points',
        xycoords=ccrs.PlateCarree()._as_mpl_transform(ax),
        color='#8A2220', fontsize=8, fontweight='500',
        ha='left', va='bottom', zorder=6,
    )

    # NW corner callout
    nw_lon, nw_lat = aoi_west, aoi_north
    ax.plot(nw_lon, nw_lat, marker='o', color='#C8322F', markersize=7,
            markeredgewidth=1.5, markeredgecolor='white',
            transform=ccrs.PlateCarree(), zorder=6)
    ax.annotate(
        f"NW corner\n({nw_lat:.1f}°N, {abs(nw_lon):.0f}°W)",
        xy=(nw_lon, nw_lat), xytext=(-10, 8), textcoords='offset points',
        xycoords=ccrs.PlateCarree()._as_mpl_transform(ax),
        color='#8A2220', fontsize=8, fontweight='500',
        ha='right', va='bottom', zorder=6,
    )

    # -------------------------------------------------------------------------
    # ISS LIS ground tracks (great-circle, extended beyond detection endpoints)
    # -------------------------------------------------------------------------
    for p in iss_passes:
        lon1, lat1 = p["p1"]
        lon2, lat2 = p["p2"]
        lons, lats = great_circle_extend(
            lon1, lat1, lon2, lat2, p["ext_start"], p["ext_end"], n=120,
        )
        ax.plot(lons, lats, color=p["color"], linewidth=2.2,
                linestyle=p["linestyle"], alpha=0.9, solid_capstyle='round',
                transform=ccrs.Geodetic(), zorder=7)

        # Arrow head at the end
        head_lons, head_lats = lons[-6:], lats[-6:]
        ax.annotate(
            '', xy=(head_lons[-1], head_lats[-1]),
            xytext=(head_lons[0], head_lats[0]),
            xycoords=ccrs.PlateCarree()._as_mpl_transform(ax),
            textcoords=ccrs.PlateCarree()._as_mpl_transform(ax),
            arrowprops={'arrowstyle': '->', 'color': p["color"], 'lw': 2.0,
                        'shrinkA': 0, 'shrinkB': 0},
            zorder=8,
        )

    # -------------------------------------------------------------------------
    # Title
    # -------------------------------------------------------------------------
    if title is None:
        title = (
            f"GLM satellite coverage over {aoi_label}\n"
            "Zenith-angle thresholds (55° / 65° / 70°) vs ISS LIS ground tracks"
        )
    ax.set_title(title, fontsize=12, pad=12)

    # -------------------------------------------------------------------------
    # Legend
    # -------------------------------------------------------------------------
    legend_items = [
        Patch(facecolor='#E24B4A', alpha=0.15, edgecolor='#C8322F',
              linewidth=2, label=aoi_label),
        Line2D([0], [0], color='#0F6E56', linewidth=1.8,
               label='GOES-18 zenith rings'),
        Line2D([0], [0], color='#185FA5', linewidth=1.8,
               label='GOES-16 zenith rings'),
    ]
    for p in iss_passes:
        legend_items.append(
            Line2D([0], [0], color=p["color"], linewidth=2.2,
                   linestyle=p["linestyle"],
                   label=f"{p['label']}: {p['time']}")
        )
    legend_items.extend([
        Line2D([0], [0], color='#666666', linewidth=1.5, linestyle='-',
               label='55° zenith (good | marginal)'),
        Line2D([0], [0], color='#666666', linewidth=1.3,
               linestyle=(0, (6, 3)),
               label='65° zenith (marginal | degraded)'),
        Line2D([0], [0], color='#666666', linewidth=1.0,
               linestyle=(0, (2, 3)),
               label='70° zenith (degraded | very poor)'),
    ])
    ax.legend(handles=legend_items, loc='center left', fontsize=8,
              framealpha=0.95, edgecolor='#cccccc', fancybox=True)

    # -------------------------------------------------------------------------
    # Output
    # -------------------------------------------------------------------------
    if output_dir is None:
        # Default: <repo>/docs/img/
        repo_root = Path(__file__).resolve().parents[3]
        output_dir = repo_root / "docs" / "img"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    png_path = output_dir / f"{output_stem}.png"
    svg_path = output_dir / f"{output_stem}.svg"
    fig.savefig(png_path, dpi=150, bbox_inches='tight', facecolor='white')
    fig.savefig(svg_path, bbox_inches='tight', facecolor='white')
    print(f"wrote {png_path} ({png_path.stat().st_size / 1024:.1f} KB)")
    print(f"wrote {svg_path} ({svg_path.stat().st_size / 1024:.1f} KB)")
    plt.close(fig)

    return png_path, svg_path


# -----------------------------------------------------------------------------
# Default: the 2023-06-04 Manitoba figure for docs/glm_sensor_coverage.md
# -----------------------------------------------------------------------------
MANITOBA_AOI_BBOX = (-109.0, 42.9375, -91.0, 53.0625)
MANITOBA_AOI_LABEL = "Manitoba AOI (2023-06-04)"
MANITOBA_ISS_PASSES = [
    {
        "p1": (-104.7, 44.5), "p2": (-90.5, 51.8),
        "ext_start": 5, "ext_end": 5,
        "label": "Pass 1", "time": "19:41 UTC · 476 flashes · ASC",
        "color": "#6C5CE7", "linestyle": "-",
    },
    {
        "p1": (-106.3, 48.2), "p2": (-90.7, 53.9),
        "ext_start": 5, "ext_end": 5,
        "label": "Pass 2", "time": "21:17 UTC · 400 flashes · ASC",
        "color": "#A29BFE", "linestyle": (0, (5, 3)),
    },
    {
        "p1": (-106.4, 54.1), "p2": (-90.5, 46.4),
        "ext_start": 5, "ext_end": 5,
        "label": "Pass 3", "time": "22:55 UTC · 341 flashes · DESC",
        "color": "#E84393", "linestyle": (0, (2, 3)),
    },
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-stem', default='glm_coverage_manitoba',
                        help='filename stem (no extension) for SVG + PNG output')
    parser.add_argument('--output-dir', type=Path, default=None,
                        help='output directory (default: <repo>/docs/img/)')
    args = parser.parse_args()

    plot_glm_coverage(
        aoi_bbox=MANITOBA_AOI_BBOX,
        aoi_label=MANITOBA_AOI_LABEL,
        iss_passes=MANITOBA_ISS_PASSES,
        output_stem=args.output_stem,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()

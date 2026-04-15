# Workflows

Day-to-day command sequences for the most common scintilla tasks. For the architectural overview, see [`GLM_Lightning_Pipeline.md`](GLM_Lightning_Pipeline.md). For installation and credential setup, see [`INSTALL.md`](INSTALL.md).

All commands assume the `scintilla` conda env is active and you're running from the repo root. Output paths are written under `$SCINTILLA_DATA_DIR` (default `./data`).

---

## Areas of interest (AOIs) are the unit of work

Scintilla is largely oriented around **areas of interest** — rectangular geographic regions, stored as GeoJSON files in `data/aois/<name>_aoi.geojson`, that define *where* a storm happened. Almost every tool in the pipeline takes an `--aoi <name>` argument, and "starting a new piece of work" almost always means "drawing a new AOI".

An AOI has four jobs:

1. **It defines the spatial clip region** for raw GLM NetCDFs — `cut_glm_aoi_chips.py` and `movie_map.py` reproject the AOI polygon into the GOES-R geostationary projection and clip each frame to it.
2. **It bounds the ISS LIS flash filter** — `find_isslis_overlaps.py` asks "which ISS passes crossed this rectangle, and how many flashes did they record inside it?"
3. **It sets the map extent** for animations — `movie_map.py` uses the AOI bounds to frame every video.
4. **It anchors the local timezone** — the AOI centroid is fed through `timezonefinder` so that `--start-date`/`--end-date` are interpreted in the region's actual local time, not UTC.

Because of job #3, AOIs for animations should be **roughly 16:9** (the standard video aspect ratio). More on that below.

### Drawing a new AOI

Easiest path: go to <https://geojson.io>, draw a rectangle around the region you care about, and click "Save → GeoJSON". Rename the file to `<name>_aoi.geojson` and drop it into `data/aois/`. Scintilla's `--aoi` argument will pick it up automatically next time.

Add a `"name"` property and optionally a `"peak_event"` description in the properties block — scintilla doesn't read them, but six months from now you'll be grateful you wrote down *why* you drew the box where you did.

You can also use QGIS or any other GIS tool. The only requirement is a single-feature Polygon in a FeatureCollection, in WGS84 (EPSG:4326). Rectangles work best but any polygon will do.

### 16:9 aspect-ratio variant for video framing

mp4 animations target 1920×1080 (16:9). If your hand-drawn AOI is off — say 1.5:1 or 2:1 — the rendered frames will have wasted basemap margins, or worse, the storm will spill outside the visible frame. Generate a sibling 16:9 AOI with `aoi_to_16-9.py`:

```bash
./src/scintilla/tools/aoi_to_16-9.py --aoi <name> --output-name <name>_169
```

This writes `data/aois/<name>_169_aoi.geojson` alongside the original, with the latitude range expanded or contracted to land exactly on 16:9. Keep both: the original for gif previews and the 169 variant for the final mp4/YouTube render.

Example: the Manitoba AOI shipped with this repo (`mb-2023-06-04_169_aoi.geojson`) came from a hand-drawn 18°×10° box that was *almost* 16:9 (1.800). `aoi_to_16-9.py` nudged it to 18°×10.125° (1.7778 = exactly 16/9).

### Programmatic AOI manipulation

For scripted operations (bbox queries, intersection checks, batch generation from a list of coordinates), see `src/scintilla/tools/aoi_tool.py`. Covers listing, expanding, clipping, and converting AOIs between formats.

### What's the right AOI size?

Big enough to contain the whole storm complex, plus a little margin, so you can see the storm move across the frame. For convective storm systems that's typically a 5-10° box. **Don't make it tight** — the [cross-sensor validation doc](GLM_ISSLIS_cross_sensor_validation.md) shows that AOIs too small to contain the full storm produce misleading lightning centroids (the storm's brightest cells end up *outside* the clip region and the GLM/ISS LIS agreement appears to break down).

---

## Running the demo

The 23 MB bundled demo renders a real storm animation with no setup beyond `conda activate`:

```bash
./src/scintilla/animate/movie_map.py \
    --aoi us-mexico-border \
    --start-date "2023-07-30 21:10" --end-date "2023-07-30 21:30" \
    --layers glm isslis \
    --output-format mp4
```

Times are in **AOI-local time** (MST for this AOI — Arizona, UTC-7 — so `21:10` = `04:10 UTC` the next day). 21 frames of GLM lightning overlaid with one ISS LIS pass (~229 flashes), encoded to `data/movies/us-mexico-border_2023-07-30_2110_2023-07-30_2130.mp4`.

---

## GLM-only animation (the standalone workflow)

When you just want a lightning animation for an arbitrary storm on a date within GLM's coverage window (April 2023 onwards, roughly). This is the four-step loop most new AOIs go through.

### 1. Search for granules

```bash
./src/scintilla/tools/get_granules.py \
    --aoi <aoi-name> \
    --start-date YYYY-MM-DD --end-date YYYY-MM-DD \
    --mission GLM --goes-satellite G18 \
    --max-items 2000
```

Queries NASA's CMR via `earthaccess` and writes a CSV of matching granule URLs to `data/granule_metadata/<aoi>/GLM_<aoi>_<start>_<end>.csv`. GLM granules come roughly once per minute, so a full UTC day is ~1,440 rows.

Defaults to G18 (GOES-West). Use `--goes-satellite G16` for GOES-East — pick based on which satellite has the better zenith-angle view of your AOI. See [`glm_sensor_coverage.md`](glm_sensor_coverage.md) for the geometry.

### 2. Download the raw NetCDF files

```bash
./src/scintilla/tools/download_from_urls.py \
    --aoi <aoi-name> \
    --start-date YYYY-MM-DD --end-date YYYY-MM-DD \
    --mission GLM --goes-satellite G18 \
    --max-items 2000
```

Reads the CSV from step 1 and streams each file into `data/glm_raw/<sat>/<Y>/<M>/<D>/`. Idempotent — already-downloaded files are skipped.

A full day is ~1 GB per satellite. If you only need a few hours, trim `--max-items` or (better) use a tighter `--start-date`/`--end-date`.

### 3. Animate

```bash
./src/scintilla/animate/movie_map.py \
    --aoi <aoi-name> \
    --start-date "YYYY-MM-DD HH:MM" --end-date "YYYY-MM-DD HH:MM" \
    --goes-satellite G18 \
    --output-format mp4
```

`movie_map.py` clips the raw NetCDFs to the AOI on the fly (writing per-frame GeoTIFFs to `data/glm_clips/<aoi>/` as it goes), then walks the time window and encodes frames to mp4.

Key flags:
- `--start-date` / `--end-date` are interpreted in the AOI's **local timezone** (derived from the AOI polygon centroid via `timezonefinder`). The end time is inclusive.
- `--layers glm isslis` adds ISS LIS flash overlays if there's a matching orbit in `data/isslis/`.
- `--framerate 4` (default) → ~1 min of storm per second of video at default 1-min cadence.
- `--output-format gif` for a small looping gif instead of mp4.

---

## GLM + ISS LIS combined workflow

When the storm falls within the ISS LIS mission window (2017-2023 November), you can overlay the low-earth-orbit flash markers on top of the geostationary GLM raster. This is the demo path, and it's the strongest visual — two completely independent sensors agreeing cell-by-cell on where the lightning is.

### 1. Find dates with ISS LIS coverage over your AOI

```bash
./src/scintilla/tools/find_isslis_overlaps.py --aoi <aoi-name>
```

Scans the pre-built parquet index of all ISS LIS flashes and reports dates/times when the ISS was passing over your AOI's bounding box. Output includes flash counts per pass so you can pick the densest ones.

### 2. Download the ISS LIS orbit files for the dates you want

ISS LIS granules live in `data/isslis/<Y>/<M>/<D>/`. If you're missing them, use `get_granules.py --mission ISSLIS` + `download_from_urls.py --mission ISSLIS`. The parquet index (`data/isslis/isslis_flash_index.parquet`) is regenerated by `backfill_isslis.py` when you add new raw files.

### 3. Run steps 1-3 of the GLM workflow above

Same as standalone GLM — `get_granules.py` + `download_from_urls.py` + `movie_map.py`. Just be sure to pass `--layers glm isslis` to the final `movie_map.py` call so the flash overlay is enabled.

### Sanity-check the cross-sensor alignment

If you're working on a new AOI and want to confirm GLM and ISS LIS agree, pick a date with a large ISS LIS pass (say 100+ flashes) and render the combined video. The magenta ISS LIS markers should overlay the GLM raster to within one GLM grid cell (~8 km). See [`GLM_ISSLIS_cross_sensor_validation.md`](GLM_ISSLIS_cross_sensor_validation.md) for the validation numbers — if your new AOI shows a significantly larger offset, the most likely cause is an AOI that's too small to contain the storm.

---

## ISS LIS discovery — finding interesting storms

When you don't have a specific date in mind, work backwards from "where did it actually rain lightning?". The `--discover` mode bins every flash in the parquet index into 1°×1° cells and surfaces the densest ones.

### Single-day hotspots (one-off storm events)

```bash
./src/scintilla/tools/find_isslis_overlaps.py --discover --mode by-day --year 2023 --top 10
```

Returns `(date, lat, lon, flash_count)` tuples. Each row is a candidate storm. Pick one, draw an AOI around it, run the GLM workflow. Typical output on a good storm year: 300-700 flashes in a single cell on a single day.

### All-time hotspots (persistent regions)

```bash
./src/scintilla/tools/find_isslis_overlaps.py --discover --mode all-time --top 10
```

Returns cells that consistently get hit across the entire ISS LIS record. Classic results: Lake Maracaibo (Catatumbo), Lake Kivu, northern Pakistan, central Africa. Useful for picking regions to build long-duration climatologies rather than single storms.

### Optional filters

- `--year YYYY` — restrict to a single year
- `--bbox W S E N` — restrict to a bounding box (e.g. CONUS: `--bbox -125 24 -65 50`)
- `--min-flashes N` — minimum flash count per cell
- `--top N` — number of rows to return

See [`README_ISSLIS.md`](README_ISSLIS.md) for the full index architecture, the v2/v3 dataset distinction, and how flashes are indexed.

---

## Inspecting what's on disk

When you lose track of what you've downloaded for which AOI:

```bash
./src/scintilla/tools/inventory_data.py --aoi <name>
```

Reports which dates have raw GLM files, which have ISS LIS orbits, and what clips/movies have been generated. Useful for confirming a download completed and for avoiding re-downloads.

---

## Troubleshooting common workflow issues

### "no granules found" from `get_granules.py`

Either the date range is outside the mission's coverage, the AOI bbox is wrong, or NASA EarthData credentials aren't working. Test the credentials with `python -c "import earthaccess; earthaccess.login(strategy='netrc')"`. For GLM, the GHRC `glmgoesL3` collection only covers April 2023 onwards.

### `movie_map.py` renders blank frames

Usually means no GLM activity in the chosen time window — not a bug. Double-check with `./src/scintilla/tools/sum_glm_chips.py --aoi <name> --start-date ... --end-date ...` which produces a single cumulative image showing where (and whether) any lightning exists in the range.

### End-time feels off by one minute

`movie_map.py` treats `--end-date` as inclusive (21:10-21:30 gives 21 frames, not 20). If you're comparing against other tools that use half-open intervals, add one minute to your end time when importing the window from scintilla.

### Timestamp confusion between tools

`find_isslis_overlaps.py` reports times in UTC. `movie_map.py` interprets `--start-date`/`--end-date` in the **AOI's local timezone**. When copying an overlap time into `movie_map`, convert it yourself or pass UTC times and accept that the frame titles will be displayed in local time.

# ISS LIS in scintilla

ISS LIS (Lightning Imaging Sensor on the International Space Station) is one of two lightning datasets scintilla animates. Unlike GLM, which is geostationary and produces continuous full-disk raster coverage, **ISS LIS is sparse**: every record in the source data is a single lightning flash event captured during one of the ISS's ~16 daily orbits as its narrow swath passes over a thunderstorm. There is no background, no zero-flash padding, no raster — just point events.

This sparseness is exactly what makes it useful for AOI discovery: every record is a positive signal, no false-detection filtering needed.

## Mission timeline

| | |
|---|---|
| First light | March 2017 (STP-H5 payload, ISS Columbus External Payload Facility) |
| Last data observed in our archive | 2023-11-16 |
| Mission end | ~December 2023 (per UCAR climate data guide) |
| Latitudinal coverage | ±55° (matches ISS orbital inclination) |
| Longitudinal coverage | full ±180° |
| Orbits per day | ~16 (~90 min orbital period) |
| Files per day | ~14 average (~93% of expected, gaps from attitude maneuvers etc.) |

## Datasets — v2_fin vs v3_fin

Two coexisting reprocessings exist on the GHRC DAAC:

| Collection | earthaccess `short_name` | `version` | Filename stem | Notes |
|---|---|---|---|---|
| v2 final | `isslis_v2_fin` | `2` | `ISS_LIS_SC_V2.1_*` | Older reprocessing. Files in CMR are mostly `.hdf`. |
| **v3 final** | `isslis_v3_fin` | `3` | `ISS_LIS_SC_V3.0_*` | **Current.** Newer calibration / event-grouping. CMR registers each orbit as **two granules** — one `.nc` and one `.hdf`. Backfill tooling dedupes to one per orbit (preferring `.nc`). |
| v2 backgrounds | `isslisg_v2_fin` | `2` | — | Background dataset (per-orbit calibration backgrounds), not used by scintilla. |

`MISSION_TO_EARTHDATA_DICT['ISSLIS']` in `src/scintilla/common/defines.py` points at v3. Note: the version field must be `'3'` (no leading zeros) — earthaccess silently returns 0 hits with `'003'`, which used to be a latent bug.

### Why both versions are on disk

The 2020-2023 files were downloaded as v2.1 `.nc` (~55 GB, 19,746 files) before v3 existed. The 2017-2019 backfill uses v3, so the on-disk dataset is intentionally **mixed-version**:

- 2017-03 → 2019-12: V3.0 `.nc` (filed by `backfill_isslis.py`)
- 2020-01 → 2023-11: V2.1 `.nc` (legacy)

`find_isslis_overlaps.py` reads both transparently; the parquet index unions them. v3 reprocessing improves geolocation (sub-km) and calibration but does not materially change regional flash counts at the 1° scale used by `--discover`, so re-downloading 2020-2023 in v3 is **not worth ~250 GB** of additional bandwidth for our use case. Validate cheaply if ever in doubt by downloading one V3 month for 2020 and comparing top hot-cells to the V2.1 numbers — they will be effectively identical.

## File formats — `.nc` and `.hdf` are interchangeable

The v3 GHRC catalog hosts each orbit as both NetCDF-4 (`.nc`) and HDF4 (`.hdf`). Both formats:

- Open cleanly with `netCDF4.Dataset(path, 'r')` in this conda env (no special HDF4 build flag needed)
- Contain the same variables (`lightning_flash_lat`, `lightning_flash_lon`, `lightning_flash_TAI93_time`, `lightning_flash_radiance`, `lightning_flash_delta_time`)
- Are interchangeable downstream

`backfill_isslis.py` dedupes the `.nc`/`.hdf` granule pairs and prefers `.nc` to match the existing on-disk convention. `find_isslis_overlaps.py:build_index` globs both extensions so a mixed-format dataset Just Works.

## On-disk layout

```
/opt/scintilla/data/isslis/
├── isslis_flash_index.parquet         # built by find_isslis_overlaps.py --rebuild-index
├── 2017/<MM>/<DD>/ISS_LIS_SC_V3.0_*.nc
├── 2018/<MM>/<DD>/ISS_LIS_SC_V3.0_*.nc
├── 2019/<MM>/<DD>/ISS_LIS_SC_V3.0_*.nc
├── 2020/<MM>/<DD>/ISS_LIS_SC_V2.1_*.nc
├── 2021/<MM>/<DD>/ISS_LIS_SC_V2.1_*.nc
├── 2022/<MM>/<DD>/ISS_LIS_SC_V2.1_*.nc
└── 2023/<MM>/<DD>/ISS_LIS_SC_V2.1_*.nc
```

The Y/M/D split is by the orbit-start date in UTC, parsed from the filename's `YYYYMMDD` stem.

## Workflow

```
              ┌─────────────────────────┐
              │   GHRC DAAC (CMR)       │
              └────────────┬────────────┘
                           │ earthaccess
                           ▼
       ┌───────────────────────────────────────┐
       │  backfill_isslis.py                   │
       │  (one-shot per missing date range)    │
       │  → data/isslis/<Y>/<M>/<D>/*.nc       │
       └────────────┬──────────────────────────┘
                    │
                    ▼
       ┌───────────────────────────────────────┐
       │  find_isslis_overlaps.py              │
       │  --rebuild-index                      │
       │  → data/isslis/isslis_flash_index.parquet
       └────────────┬──────────────────────────┘
                    │
        ┌───────────┴───────────────┐
        ▼                           ▼
┌──────────────────┐     ┌────────────────────────┐
│  --discover      │     │  --aoi <name>          │
│  find new        │     │  query an existing AOI │
│  hotspots        │     │  for flash overlaps    │
└──────────────────┘     └─────────┬──────────────┘
                                   │
                                   ▼
                       ┌─────────────────────────┐
                       │  movie_map.py           │
                       │  --layers isslis [glm]  │
                       │  reads parquet index    │
                       └─────────────────────────┘
```

## Tooling

- **`src/scintilla/tools/backfill_isslis.py`** — download missing ISS LIS files for a date range. Idempotent (skips files already on disk), month-by-month for resumability, dedupes v3 `.nc`/`.hdf` granule pairs.
  ```bash
  ./backfill_isslis.py --dry-run                                # default range, no download
  ./backfill_isslis.py --start-date 2019-12-01 --end-date 2019-12-31
  ./backfill_isslis.py                                          # full pre-2020 backfill
  ```

- **`src/scintilla/tools/find_isslis_overlaps.py`** — build / query the parquet flash index.
  ```bash
  ./find_isslis_overlaps.py --rebuild-index                     # rescan all .nc/.hdf files
  ./find_isslis_overlaps.py --aoi tucson                        # flashes inside an AOI
  ./find_isslis_overlaps.py --discover --mode all-time --top 20 # persistent hotspots
  ./find_isslis_overlaps.py --discover --mode by-day --year 2023 --top 20  # storm events
  ./find_isslis_overlaps.py --discover --bbox -85 30 -75 35 --mode by-day  # region-filtered
  ```
  `--discover` excludes cells whose center falls inside any existing AOI's bounding box, so the output is *new* candidates rather than rediscoveries.

- **`src/scintilla/animate/movie_map.py --layers isslis`** — reads the parquet index (not the raw files) and overlays flash points on the animation.

## External references

- [GHRC ISS LIS NetCDF data recipe](https://ghrc.nsstc.nasa.gov/home/data-recipes/iss-lis-lightning-flash-location-quickview-using-python-30-and-gis) — original Python loading example
- [ISS LIS dataset documentation PDF](https://ghrc.nsstc.nasa.gov/pub/lis/iss/doc/isslis_dataset.pdf) — variable definitions, file structure
- [UCAR climate data guide — TRMM and ISS LIS](https://climatedataguide.ucar.edu/climate-data/lightning-data-trmm-and-iss-lightning-image-sounder-lis-towards-global-lightning) — mission context, end-of-mission note
- [NASA GHRC lightning landing page](https://ghrc.nsstc.nasa.gov/lightning/)

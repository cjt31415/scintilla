# Decisions

Architectural decisions and rejected approaches.

## 2026-04-11: GLM–ISS LIS cross-sensor validation confirms pipeline accuracy

**Context:** Adding ISS LIS flash overlay to GLM animations initially showed a ~50 km offset between the two sensors. After extensive investigation — comparing full-disk GLM, clipped chips, ISS LIS flash points, and manual GOES-R coordinate transforms — the offset was traced to using an AOI (tucson-area_169) that was too small to contain the main storm cell.

**Decision:** No code changes needed. The pipeline is spatially accurate. When re-tested with the arizona AOI, GLM and ISS LIS agree to ~9 km (one GLM grid cell). See `docs/GLM_ISSLIS_cross_sensor_validation.md` for the full analysis.

**Alternatives considered:**
- Option A (pre-reproject chips to WGS84 during cutting) — rejected because the native geostationary CRS is correct
- Option B (render GLM as patches instead of imshow) — rejected because imshow rendering is also correct
- Option C (increase reprojection resolution) — rejected because the reprojection is not the source of the offset

**Consequences:** Cross-sensor demos should use large AOIs (state-level or bigger) to ensure the full storm complex is captured by both the GLM clip and the ISS LIS overlay. The `--layers glm isslis` feature is validated and ready for use.

## 2026-04-10: ISS LIS mission ended December 2023

**Context:** While building cross-sensor GLM+ISS LIS visualization, discovered that ISS LIS data only exists from 2020-01 to 2023-11.

**Decision:** The overlap window for cross-sensor work is July 2023 to November 2023. The `find_isslis_overlaps.py` tool indexes all available ISS LIS data and spatially queries it against AOIs to find usable date ranges.

**Consequences:** Cross-sensor demos must use data from this 5-month window. For any new AOI, GLM granules from this period must be downloaded via `get_granules.py` + `download_from_urls.py`.

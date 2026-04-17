# Storm gallery

Storms rendered with this pipeline. Each entry notes the AOI, time window, and what makes it interesting, then links to the YouTube renders. The deepest analysis (Manitoba's GLM-16 vs GLM-18 coverage comparison) lives in [`glm_sensor_coverage.md`](glm_sensor_coverage.md); this doc is the index.

## Manitoba 2023-06-04 — GLM coverage gap revealed by satellite swap

**AOI**: `mb-2023-06-04_169` (centered near 48°N, 100°W). **Window**: 14:00–18:30 CDT (19:00–23:30 UTC).

Running the same storm through both GLM satellites (GOES-East `G16` and GOES-West `G18`) revealed a real geometric limitation. At the northeast corner of the AOI, GOES-West sees the region at ~74° zenith angle, where its optical detection efficiency drops significantly. GOES-East, looking at the same storm from ~62° zenith, catches **80% more non-zero pixel-minutes** and **2.4× more total optical energy** — and the G16 detections overlay exactly on the ISS LIS flash markers that were standing alone in the G18 render.

- **GLM-18 (GOES-West, shows the coverage gap)**: <https://youtu.be/csoez_Rxdh8>
- **GLM-16 (GOES-East, fills the gap)**: <https://youtu.be/Ef1qxls_bjY>

Full analysis — zenith-angle math, per-corner geometry table, and a multi-satellite fusion design sketch — in [`glm_sensor_coverage.md`](glm_sensor_coverage.md). This pipeline was built to render storm animations, but the multi-satellite comparison shows it's also a usable tool for validating lightning-sensor coverage claims.

## US/Mexico border 2023-07-30 — bundled pipeline demo

**AOI**: `us-mexico-border_169`. **Window**: 21:10–21:30 MST.

The storm shipped with the repo as the runnable demo. A fresh `git clone` can render this animation with no NASA credentials — the raw GLM frames and matching ISS LIS orbit file are bundled (~23 MB). It's also the GIF embedded at the top of the README.

- **GLM + ISS LIS overlay**: <https://youtu.be/5yVm39Y9xTs>

## Tucson monsoon 2023-07-31 — ground-level pairing (looking south)

**AOI**: `tucson-area_169`. **Trail-cam window**: 11:10–19:30 MST. **Satellite render window**: 14:00–19:30 MST. No ISS LIS overflight during the window.

Cross-scale view of the same storm: a Reconyx trail camera looking south from inside the AOI captured the cell evolution from the ground while GLM-18 watched the same system from geostationary orbit. Watching both back to back gives a sense of how cloud-top GLM detections relate to what someone standing under the storm actually sees.

- **Trail camera (ground, looking south)**: <https://youtu.be/V-GN_UX9okc>
- **GLM-18 (satellite)**: <https://youtu.be/csjLWv4MKyQ>

Render filename: `tucson-area_169_2023-07-31_1400_2023-07-31_1930.mp4`.

## Tucson monsoon 2023-08-07 — ground-level pairing with ISS LIS overflight (looking northwest)

**AOI**: `tucson-area_169`. **Trail-cam window**: 13:50–20:00 MST. **Satellite render window**: 15:00–20:00 MST. ISS LIS caught **3 flashes near Green Valley** during the window.

Same cross-scale pairing as above, this time looking northwest from a different vantage. A brief ISS LIS overflight registered three flashes just south of Tucson, so this storm has all three sensor perspectives — ground camera, geostationary GLM-18, and low-Earth-orbit ISS LIS — viewing the same system within the same window.

- **Trail camera (ground, looking northwest)**: <https://youtu.be/ByGfISBm0Do>
- **GLM-18 + ISS LIS (satellite)**: <https://youtu.be/hqbLH0o647Y>

Render filename: `tucson-area_169_2023-08-07_1500_2023-08-07_2000.mp4`.

# Installation

scintilla depends on a GDAL/PROJ/GEOS/cartopy stack that is notoriously fragile on pip-only installs. A conda environment is mandatory — trying to `pip install` the geospatial dependencies directly will almost always end in ABI mismatches or missing C headers.

## 1. Conda environment

Install [miniconda](https://docs.conda.io/en/latest/miniconda.html) or [miniforge](https://github.com/conda-forge/miniforge) if you don't already have it, then:

```bash
git clone https://github.com/cjt31415/scintilla.git
cd scintilla
conda env create -f environment.yml
conda activate scintilla
```

The env file pins Python 3.11-3.13 and pulls the full geospatial stack (GDAL, PROJ, GEOS, cartopy, rasterio, fiona, geopandas, rioxarray, xarray, netCDF4, h5py, pyarrow, scikit-image, ffmpeg, opencv) from conda-forge. Pure-Python deps (earthaccess, folium, joblib, etc.) are installed via pip inside the same env, and the last step of the env file runs `pip install -e .` so that `scintilla` itself is importable as an editable package.

Verify the install:

```bash
python -c "import scintilla; import cartopy; import rasterio; print('ok')"
pytest tests/
```

The test suite is fast (a few seconds) and doesn't hit the network.

## 2. Run the demo

The repo ships with a ~23 MB demo subset, so you can render a real storm animation with no further setup:

```bash
./src/scintilla/animate/movie_map.py \
    --aoi us-mexico-border \
    --start-date "2023-07-30 21:10" --end-date "2023-07-30 21:30" \
    --layers glm isslis \
    --output-format mp4
```

Output lands at `data/movies/us-mexico-border_2023-07-30_2110_2023-07-30_2130.mp4`. **If this works, your install is good.**

If you want to point scintilla at a larger data directory (for real work beyond the demo), set `SCINTILLA_DATA_DIR`:

```bash
export SCINTILLA_DATA_DIR=/path/to/your/big/data/dir
```

`SCINTILLA_DATA_DIR` defaults to `./data` (the shipped demo subset) when unset.

## 3. NASA EarthData credentials (optional, required for real downloads)

The demo works from pre-staged data. To search for and download *new* GLM or ISS LIS granules, you need a free NASA EarthData account:

1. Sign up at <https://urs.earthdata.nasa.gov/users/new>. It takes about two minutes.
2. Put your credentials in `~/.netrc`:

   ```
   machine urs.earthdata.nasa.gov
     login <your-username>
     password <your-password>
   ```

3. `chmod 600 ~/.netrc` — required or `earthaccess` will refuse to read it.

scintilla uses `earthaccess.login(strategy="netrc", persist=True)` for authentication, so once `.netrc` is in place you should never be prompted again.

Test the credentials:

```bash
python -c "import earthaccess; earthaccess.login(strategy='netrc'); print('ok')"
```

## 4. Stadia Maps API token (optional, for branded basemaps)

The default basemap tiles work without any credentials. If you want the cleaner Stadia Maps basemap style used in the reference YouTube video:

1. Get a free API token at <https://client.stadiamaps.com/>.
2. Copy `.env.example` to `.env` and fill in:

   ```
   STADIA_API_TOKEN=your-token-here
   ```

3. `.env` is gitignored — your token will not accidentally be committed.

## Troubleshooting

### `ImportError: cannot find PROJ library` or `GDAL version mismatch`

Almost always caused by having another GDAL/PROJ install on your `PATH` (often from Homebrew on macOS). Deactivate the conda env, check:

```bash
which gdal-config
echo $PKG_CONFIG_PATH
```

and make sure nothing is shadowing the conda-provided versions. Recreate the env cleanly with `conda env remove -n scintilla && conda env create -f environment.yml` if the mismatch persists.

### `ffmpeg: command not found`

ffmpeg is pulled in by `environment.yml` and should live inside the conda env. If it's missing, check that you activated the env (`conda activate scintilla`) and that `which ffmpeg` points inside `.../miniconda3/envs/scintilla/bin/`.

### `TypeError` or `AttributeError` from cartopy/rasterio

Usually an ABI mismatch from a stale pip-installed package in the env. The fix is `conda env remove -n scintilla && conda env create -f environment.yml` — don't try to `pip install --upgrade` your way out of it.

### macOS: `clang: error: no such file or directory` during install

You're missing Xcode Command Line Tools. Run `xcode-select --install`, then retry the env create.

### Linux: HDF5 warnings from `netCDF4`

Harmless. If they're noisy, set `HDF5_DISABLE_VERSION_CHECK=1` before running scintilla commands.

### The demo command fails with "no granules found"

Make sure you're running from the repo root and that `SCINTILLA_DATA_DIR` is either unset (so it defaults to `./data`) or pointed at a directory that contains the demo subset. Verify with:

```bash
ls data/glm_raw/G18/2023/7/31/   # should show 21 .nc files
ls data/isslis/2023/7/31/        # should show 1 .nc file
ls data/aois/                    # should include us-mexico-border_aoi.geojson
```

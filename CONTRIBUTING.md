# Contributing to scintilla

Thanks for your interest! Scintilla is a small project and most contributions will be welcome — bug reports, doc fixes, new AOIs, new storm highlight analyses, or code improvements.

## Before you start

If your contribution is non-trivial (new feature, architectural change, new external dependency), please open an issue first to discuss the approach. For small fixes (typos, bug patches, doc clarifications), just open a PR.

## Setting up a dev environment

Follow [`docs/INSTALL.md`](docs/INSTALL.md) to get the conda env installed and the demo command running. Then:

```bash
conda activate scintilla
pytest tests/          # must pass before submitting a PR
ruff check src/ tests/ # must pass before submitting a PR
```

Both are also run in CI on every PR (see `.github/workflows/test.yml`), so you'll find out one way or another.

## Making changes

- **Keep PRs focused.** One logical change per PR. It's fine to send multiple small PRs rather than one large one.
- **Add or update tests** when you change behavior. The `tests/` directory uses plain pytest; follow the patterns in `test_utils.py` and `test_map_time.py`.
- **Fix ruff warnings in files you touch**, not just the ones you introduced — the project follows a "leave it cleaner than you found it" rule. The ruff config is in `pyproject.toml` (line length 100, `py311` target, standard lint rules).
- **Don't commit credentials.** `.env` is gitignored for a reason. If you accidentally stage real NASA EarthData credentials or Stadia API tokens, unstage them before pushing.
- **Don't commit downloaded data.** Raw GLM/ISS LIS files are large, date-specific, and easy to re-download. `.gitignore` already excludes `production_data/` and `*.nc`.

## Commit messages

Simple convention borrowed from the project's internal history:

```
[PREFIX] short description

optional longer body
```

Common prefixes:

- `[IMPL]` — working implementation of a feature
- `[FIX]` — bug fix
- `[REFACTOR]` — restructuring without behavior change
- `[DOCS]` — documentation only
- `[TEST]` — test-only changes
- `[CI]` — CI/build changes

## Adding a new AOI or highlight analysis

Scintilla is AOI-driven, and the strongest kind of contribution is a new storm event worth animating. To submit one:

1. Draw the AOI via <https://geojson.io> following the conventions in [`docs/WORKFLOWS.md`](docs/WORKFLOWS.md). Both the hand-drawn and `_169` variants are useful.
2. Include a short Markdown writeup in `docs/` explaining: what the storm was, why it's interesting, the ISS LIS pass count if applicable, the GLM satellite used, and a reference to the rendered mp4/gif. See `docs/glm_sensor_coverage.md` as an example of the style.
3. Don't commit the raw GLM NetCDFs — just the AOI files and the writeup. Users can re-download the data with the workflow in `docs/WORKFLOWS.md`.

## Reporting bugs

Open a GitHub issue with:

- What you ran (exact command).
- What you expected to happen.
- What actually happened (error text, screenshot, or a link to the broken mp4).
- Your platform (macOS / Linux / which conda env version).

If the bug is in the GDAL/PROJ/cartopy install stack, please check [`docs/INSTALL.md#troubleshooting`](docs/INSTALL.md) first — most install issues there have known fixes.

## Code of conduct

Be kind, assume good faith, and don't be a jerk. That's it.

## License

By contributing you agree that your contributions are licensed under the MIT License (see [`LICENSE`](LICENSE)).

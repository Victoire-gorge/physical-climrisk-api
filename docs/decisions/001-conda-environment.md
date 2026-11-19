# 001. Dependencies managed with conda-forge and conda-lock

## Context
CLIMADA depends on compiled geospatial libraries (GDAL, PROJ, GEOS, HDF5). Installing them with
pip is fragile, especially on Apple Silicon. The service will also run in Linux containers
(amd64), so the same dependency set must resolve on both macOS arm64 and Linux.

## Options
1. **Poetry / pip**: the usual Python tooling, but compiled geospatial dependencies often fail to
   build or pull mismatched binaries.
2. **conda `environment.yml` alone**: easy, but not reproducible (versions float between installs).
3. **`micromamba env export --explicit`**: exact, but only for the platform it runs on.
4. **`environment.yml` + `conda-lock.yml`**: human-edited spec plus an exact, multi-platform lock.

## Decision
Option 4. `environment.yml` is the single source of truth for what we depend on;
`conda-lock.yml` pins exact builds for `osx-arm64` (development) and `linux-64` (Docker, CI,
cloud). `pyproject.toml` only describes the package and lists no dependencies, to avoid two
sources of truth. The package is installed with `pip install -e . --no-deps`.

Dev tools (pytest, ruff, httpx) live in the same environment for simplicity. conda-lock itself
is a tooling dependency and lives in a separate environment.

## Consequences
- Reproducible installs on the laptop, in CI and in the container.
- The lock must be regenerated after every change to `environment.yml`
  (`conda-lock lock -f environment.yml -p osx-arm64 -p linux-64`).
- The Docker image copies the environment files before the code, so the dependency layer is
  cached across code changes.
- Splitting runtime and dev dependencies (smaller production image) is a possible later step,
  once image size is measured.

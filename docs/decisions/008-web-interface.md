# 008. Web interface: an educational Streamlit client of the API

## Context
The API answers in JSON, which suits programs but not a first reading. An interface should
show where each site is matched on the hazard grid (a 4.6 x 3.3 km cell, not the exact point),
explain the insurance metrics it returns, and show how the API itself works. It should also be
reachable from the README without installing anything (hosting is a later step).

## Options
**Framework**
1. **Streamlit**: Python only, tables, charts and a map in a few hundred lines.
2. A JavaScript front end (React with a map library): more control, a second language and build.

**Map**
1. **pydeck**, shipped with Streamlit: points, lines and polygons (the grid cells).
2. `st.map`: points only, so no matching line and no cell.
3. folium with streamlit-folium: two more dependencies for a similar result.

**Relation to the API**
1. **HTTP client**, like any other client, never importing `climrisk`.
2. Import the science modules directly: faster to write, but couples the interface to the
   server code and hides the API it is meant to explain.

**Environment**
1. **Separate environment** (`ui/environment.yml`, `ui/conda-lock.yml`): Streamlit, pydeck,
   requests, pandas, numpy; no CLIMADA, no GDAL (589 MB on osx-arm64).
2. Add Streamlit to the API environment: simpler today, but the API image would carry it.

## Decision
Option 1 in each case.
- Three tabs. Portfolio, map and results on one page: the editable portfolio with the
  description of each site and a summary (number of sites, insured value per asset type), the
  map, then the results table, whose rows take the colour of the site status on the map (one
  colour definition, `STATUS_COLORS`). Insurance basics (hazard, exposure, vulnerability;
  vulnerability curves; AAL and PML; return period probability; diversification; limits).
  Under the hood (endpoints, status codes, server pipeline with links to the code, error
  buttons, and every request sent by the page with its `curl` equivalent).
- The portfolio comes from the demo or from an uploaded file: CSV (comma, or the `;` and decimal
  comma of a French Excel export) or JSON (the API request format, or a plain list of sites).
  Reading a file only checks its structure (required columns); site values are checked by the
  API, site by site. A CSV template (the demo portfolio) can be downloaded, and re-imports as is.
- The table shows that every row is analysed: its tick boxes only select rows to delete.
- The demo portfolio is read from the example published in the API's OpenAPI description, and
  the damage curves from `GET /v1/vulnerability-curves`: the interface holds no copy of either.
- Pure functions (cell polygon, return period probability, damage ratio, response formatting,
  `curl` command) live in `ui/logic.py` and are tested in the main test suite; `ui/app.py` holds
  the Streamlit layout and the HTTP calls.
- The API address comes from `CLIMRISK_API_URL` (default `http://127.0.0.1:8000`).
- Interface texts are in English, like the rest of the repository.

## Consequences
- The layout itself is not unit tested; it was checked with Streamlit's `AppTest` against the
  running API (analysis, error buttons, request log). The map needs a browser to be checked.
- A change of the API contract can break the interface: the endpoints it reads are the ones
  documented in 007.
- Hosting (one container serving the API and the interface) is planned with the Docker step.

# 006. Site validation: per-site report, distance thresholds in grid half-diagonals

## Context
Every endpoint must apply the same rules to a portfolio: a site judged valid by `/validate` must
never be excluded by `/analyze`. Some rules depend only on the site (value, asset type, unique
id), others on the loaded hazard (zone, distance to the matched centroid).

Every site is matched to its nearest centroid (see the exposure module). The distance then tells
how far the result is from the actual location. Measured on the Gironde river flood grid (cells of
about 4.63 x 3.3 km, 123 of 1,360 missing at sea and in the estuary):
- a site inside an existing cell is at most one half-diagonal (2.85 km) from its centroid;
- among 200,000 random points of the extent, 6.0 % are further than that (their own cell is
  missing) and 1.6 % are beyond three half-diagonals (8.55 km), all of them at sea.

## Options
**Invalid sites in a portfolio**
1. **Per-site report**: invalid sites are excluded with their reasons, the others are computed.
2. **Global rejection**: one invalid site rejects the whole request.

**Distance thresholds**
1. **Fixed distances** (2.85 km warning, 5 km exclusion): only right for one grid. On a 0.5 degree
   grid (half-diagonal about 34 km) 5 km would exclude almost every site; on a 250 m grid it would
   accept sites 25 cells away.
2. **Multiples of the cell half-diagonal**, computed from the loaded grid at each site latitude.

## Decision
Per-site report (option 1) and thresholds in half-diagonals (option 2).
- `validate_portfolio` is the only validation function. It returns one row per site with its
  status (`valid`, `warning`, `excluded`), every issue found, and the matched centroid
  (`centroid_lat`, `centroid_lon`, `distance_km`) for display on a map. `/validate` returns this
  report; `/analyze` computes the sites that are not excluded, and answers 422 if none is left.
- Issues (`Issue`, the single list): `invalid_value` (not finite or not positive),
  `unknown_asset_type`, `duplicate_site_id`, `out_of_zone` (outside the cell extent of the loaded
  hazard), `out_of_grid` (beyond 3 half-diagonals) exclude the site; `neighbour_cell` (beyond 1
  half-diagonal) is a warning, the site is evaluated with the nearest existing cell.
- All issues of a site are listed, so a client fixes everything at once.
- Two sites at the same location are valid (a wine estate declared as buildings and vines).
- Split with the API schemas: Pydantic checks only the shape of a request (missing field, text
  instead of a number) and rejects a malformed request as a whole; business rules live here.
  `asset_type` is therefore a plain string in the schema, its allowed values documented.
- `grid_geometry` runs once at load: it reads the step with CLIMADA's `get_resolution` and checks
  that the grid is regular, failing clearly otherwise.

## Consequences
- The thresholds follow the resolution of any regular grid without code changes.
- Regular means: the distinct latitudes, and the distinct longitudes, are evenly spaced by the
  step. Scattered missing cells are fine (123 in Gironde, every row and column keeps at least one
  cell). A fully missing interior row of cells (every cell at one latitude, an east-west band
  across the whole zone) or column (every cell at one longitude) is refused: it leaves a double
  gap between distinct latitudes or longitudes, which cannot be told apart from an irregular grid.
  A missing row or column on the edge only shrinks the extent. The rule will be relaxed, for
  example to accept gaps that are whole multiples of the step, when a real dataset needs it. Irregular centroids (some tropical cyclone sets) would
  need another rule, for instance based on local centroid spacing.
- A site up to 3 half-diagonals out at sea (6.7 km off the Gironde coast, for example) is evaluated
  with the nearest land cell and flagged `neighbour_cell`: the warning is the signal, not a zero.
- The exposure module still refuses CLIMADA's `-1` marker, so an out-of-zone site cannot reach
  the impact calculation by mistake.

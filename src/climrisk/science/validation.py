"""Site validation: the single set of rules shared by every endpoint.

Distance thresholds are expressed in half-diagonals of the loaded grid cell, computed at the
latitude of each site, so they follow the hazard resolution instead of a fixed distance.
See docs/decisions/006-site-validation.md.
"""

from enum import StrEnum
from typing import NamedTuple

import climada.util.coordinates as u_coord
import numpy as np
import pandas as pd
from climada.hazard import Hazard
from climada.util.constants import ONE_LAT_KM

from climrisk.science.exposure import nearest_centroid
from climrisk.science.hazard import BBox
from climrisk.science.vulnerability import AssetType

# A site inside an existing cell is at most one half-diagonal from its centroid (2.85 km for the
# Gironde river flood grid): beyond that, its own cell is missing and a neighbour cell is used.
NEIGHBOUR_CELL_HALF_DIAGONALS = 1.0
# Beyond three half-diagonals no neighbour cell touches the site either (8.55 km in Gironde).
# Measured on 200,000 random points of the Gironde extent (seed 0): 92.4 % valid, 6.0 % in a
# neighbour cell, 1.6 % out of grid, all of them at sea, more than one cell from the coast.
OUT_OF_GRID_HALF_DIAGONALS = 3.0
# Tolerance on grid spacing, as a fraction of the step. The Gironde file has spacings equal to
# the step within 1e-12 steps; 1e-6 absorbs float storage without hiding a real shift.
GRID_STEP_TOLERANCE = 1e-6

NO_CENTROID = -1  # CLIMADA's marker for an unmatched site, refused by portfolio_to_exposures


class GridGeometry(NamedTuple):
    """Regular grid of the loaded hazard: cell steps in degrees and extent of the cells."""

    lat_step_deg: float
    lon_step_deg: float
    extent: BBox


class SiteStatus(StrEnum):
    """Outcome of validation for one site."""

    VALID = "valid"
    WARNING = "warning"  # evaluated, but the result needs care
    EXCLUDED = "excluded"  # not evaluated


class Issue(StrEnum):
    """Problems a site can have. Single list, reused by the API and its documentation."""

    INVALID_VALUE = "invalid_value"
    UNKNOWN_ASSET_TYPE = "unknown_asset_type"
    DUPLICATE_SITE_ID = "duplicate_site_id"
    OUT_OF_ZONE = "out_of_zone"
    OUT_OF_GRID = "out_of_grid"
    NEIGHBOUR_CELL = "neighbour_cell"


WARNING_ISSUES = frozenset({Issue.NEIGHBOUR_CELL})  # every other issue excludes the site


def grid_geometry(hazard: Hazard) -> GridGeometry:
    """Read the grid step and cell extent of ``hazard``, checking that its grid is regular.

    Missing cells are allowed (sea, estuary), but the distinct latitudes, and the distinct
    longitudes, must be evenly spaced by the step: the half-diagonal rule assumes centroids at
    the centre of cells of constant size. Meant to run once, when the hazard is loaded.

    Raises:
        ValueError: if the distinct latitudes or longitudes are not evenly spaced.
    """
    lat, lon = hazard.centroids.lat, hazard.centroids.lon
    lat_step, lon_step = (abs(float(step)) for step in u_coord.get_resolution(lat, lon))
    for name, values, step in (("latitudes", lat, lat_step), ("longitudes", lon, lon_step)):
        spacing = np.diff(np.unique(values))
        if not np.allclose(spacing, step, rtol=GRID_STEP_TOLERANCE, atol=0):
            raise ValueError(
                f"The hazard grid is not regular: distinct {name} are not evenly spaced by "
                f"{step:g} degrees (spacings range from {spacing.min():g} to {spacing.max():g})."
            )
    extent = BBox(
        lon_min=float(lon.min()) - lon_step / 2,
        lat_min=float(lat.min()) - lat_step / 2,
        lon_max=float(lon.max()) + lon_step / 2,
        lat_max=float(lat.max()) + lat_step / 2,
    )
    return GridGeometry(lat_step_deg=lat_step, lon_step_deg=lon_step, extent=extent)


def half_diagonal_km(grid: GridGeometry, lat: np.ndarray) -> np.ndarray:
    """Half-diagonal of a grid cell at each latitude, in km.

    The north-south side is constant; the east-west side shrinks with cos(latitude).
    """
    north_south = grid.lat_step_deg * ONE_LAT_KM
    east_west = grid.lon_step_deg * ONE_LAT_KM * np.cos(np.radians(lat))
    return np.hypot(north_south / 2, east_west / 2)


def validate_portfolio(portfolio: pd.DataFrame, hazard: Hazard, grid: GridGeometry) -> pd.DataFrame:
    """Check every site of ``portfolio`` and match the evaluable ones to the hazard grid.

    Args:
        portfolio: one row per site with columns ``site_id, lat, lon, value, asset_type``.
        hazard: loaded hazard, whose centroids the sites are matched to.
        grid: geometry of the hazard grid, from ``grid_geometry``.

    Returns:
        One row per site, in portfolio order, with columns ``site_id``, ``status``, ``issues``
        (every issue of the site), ``centroid_index`` (``-1`` if out of zone), ``centroid_lat``,
        ``centroid_lon`` and ``distance_km`` (NaN if out of zone).
    """
    lat = portfolio["lat"].to_numpy(dtype=float)
    lon = portfolio["lon"].to_numpy(dtype=float)
    value = portfolio["value"].to_numpy(dtype=float)
    n_sites = len(portfolio)

    # NaN coordinates fail every comparison, so they land out of zone too.
    in_zone = (
        (lat >= grid.extent.lat_min)
        & (lat <= grid.extent.lat_max)
        & (lon >= grid.extent.lon_min)
        & (lon <= grid.extent.lon_max)
    )
    centroid_index = np.full(n_sites, NO_CENTROID)
    distance_km = np.full(n_sites, np.nan)
    matched = nearest_centroid(hazard, lat[in_zone], lon[in_zone])
    centroid_index[in_zone] = matched.index
    distance_km[in_zone] = matched.distance_km
    # Distances in half-diagonals; NaN out of zone, where comparisons below are False.
    cells_away = distance_km / half_diagonal_km(grid, lat)

    checks = {
        Issue.INVALID_VALUE: ~(np.isfinite(value) & (value > 0)),
        Issue.UNKNOWN_ASSET_TYPE: ~portfolio["asset_type"].isin(list(AssetType)).to_numpy(),
        Issue.DUPLICATE_SITE_ID: portfolio["site_id"].duplicated(keep=False).to_numpy(),
        Issue.OUT_OF_ZONE: ~in_zone,
        Issue.OUT_OF_GRID: cells_away > OUT_OF_GRID_HALF_DIAGONALS,
        Issue.NEIGHBOUR_CELL: (cells_away > NEIGHBOUR_CELL_HALF_DIAGONALS)
        & (cells_away <= OUT_OF_GRID_HALF_DIAGONALS),
    }
    issues = [[issue for issue, failed in checks.items() if failed[i]] for i in range(n_sites)]
    status = [_status(site_issues) for site_issues in issues]

    safe_index = np.where(in_zone, centroid_index, 0)  # any valid index, masked just below
    return pd.DataFrame(
        {
            "site_id": portfolio["site_id"].to_numpy(),
            "status": status,
            "issues": issues,
            "centroid_index": centroid_index,
            "centroid_lat": np.where(in_zone, hazard.centroids.lat[safe_index], np.nan),
            "centroid_lon": np.where(in_zone, hazard.centroids.lon[safe_index], np.nan),
            "distance_km": distance_km,
        }
    )


def _status(issues: list[Issue]) -> SiteStatus:
    if any(issue not in WARNING_ISSUES for issue in issues):
        return SiteStatus.EXCLUDED
    if issues:
        return SiteStatus.WARNING
    return SiteStatus.VALID

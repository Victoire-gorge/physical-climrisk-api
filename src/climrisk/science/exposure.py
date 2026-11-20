"""Exposure: match sites to hazard centroids and turn a portfolio into CLIMADA Exposures."""

from typing import NamedTuple

import climada.util.coordinates as u_coord
import numpy as np
import pandas as pd
from climada.entity import Exposures
from climada.hazard import Hazard

from climrisk.science.vulnerability import HAZARD_TYPE, AssetType, impact_function_id

VALUE_UNIT = "EUR"
IMPACT_FUNCTION_COLUMN = f"impf_{HAZARD_TYPE}"  # column name expected by ImpactCalc
CENTROID_COLUMN = f"centr_{HAZARD_TYPE}"  # same as Hazard.centr_exp_col


class NearestCentroid(NamedTuple):
    """For each site: index of the nearest hazard centroid and great-circle distance to it."""

    index: np.ndarray
    distance_km: np.ndarray


def nearest_centroid(hazard: Hazard, lat: np.ndarray, lon: np.ndarray) -> NearestCentroid:
    """Match every site to its nearest hazard centroid, in one vectorised query.

    Uses CLIMADA's ``match_coordinates`` (ball tree, haversine metric) without any threshold:
    every site gets a centroid, and the caller decides from ``distance_km`` what is too far.
    This keeps one matching for both validation and impact computation.

    CLIMADA's own threshold (an angular distance in degrees, convertible with ``km_to_degree``)
    is not used on purpose: the distance rules (warning, exclusion) are decided once, by
    validation, from ``distance_km``. Splitting them between CLIMADA and our code made the two
    disagree on sites a few metres from the limit, because the distance formulas differ slightly.
    """
    if lat.size == 0:
        return NearestCentroid(np.array([], dtype=int), np.array([], dtype=float))
    sites = np.column_stack([lat, lon])
    index = u_coord.match_coordinates(
        sites, hazard.centroids.coord, distance="haversine", threshold=np.inf
    )
    # dist_approx works on batches: one batch per site, one point on each side.
    distance_km = u_coord.dist_approx(
        lat[:, None],
        lon[:, None],
        hazard.centroids.lat[index][:, None],
        hazard.centroids.lon[index][:, None],
        method="geosphere",
        units="km",
    )[:, 0, 0]
    return NearestCentroid(index=index, distance_km=distance_km)


def portfolio_to_exposures(portfolio: pd.DataFrame, centroid_index: np.ndarray) -> Exposures:
    """Build CLIMADA Exposures from a validated portfolio and its matched centroids.

    Args:
        portfolio: one row per site with columns ``site_id, lat, lon, value, asset_type``
            (already validated).
        centroid_index: index of the hazard centroid of each site, from ``nearest_centroid``.

    Raises:
        ValueError: if the number of indices differs from the number of sites, or if an index is
            negative (CLIMADA's ``-1`` "no match" marker would silently produce a zero loss).
    """
    if len(centroid_index) != len(portfolio):
        raise ValueError(
            f"Expected one centroid index per site ({len(portfolio)}), got {len(centroid_index)}."
        )
    if np.any(centroid_index < 0):
        raise ValueError("Every site must be matched to a hazard centroid before impact.")

    data = pd.DataFrame(
        {
            "site_id": portfolio["site_id"].to_numpy(),
            "value": portfolio["value"].to_numpy(dtype=float),
            IMPACT_FUNCTION_COLUMN: [
                impact_function_id(AssetType(t)) for t in portfolio["asset_type"]
            ],
            CENTROID_COLUMN: np.asarray(centroid_index, dtype=int),
        }
    )
    return Exposures(
        data,
        lat=portfolio["lat"].to_numpy(dtype=float),
        lon=portfolio["lon"].to_numpy(dtype=float),
        crs="EPSG:4326",
        value_unit=VALUE_UNIT,
    )

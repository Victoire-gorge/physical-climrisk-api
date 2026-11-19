"""Hazard handling: restrict a CLIMADA hazard to the configured zone."""

from typing import NamedTuple

from climada.hazard import Hazard


class BBox(NamedTuple):
    """Geographic bounding box in EPSG:4326 degrees.

    Field order follows the GeoJSON / shapely convention (same as ``total_bounds``), which is
    not the order expected by CLIMADA's ``select(extent=...)``.
    """

    lon_min: float
    lat_min: float
    lon_max: float
    lat_max: float


def crop_hazard(hazard: Hazard, bbox: BBox) -> Hazard:
    """Return a copy of ``hazard`` restricted to the centroids inside ``bbox`` (boundary included).

    All events and their frequencies are kept, so annual loss statistics stay consistent with
    the source event set.

    Raises:
        ValueError: if no centroid lies inside ``bbox``. CLIMADA's ``select`` would silently
            return ``None`` in that case.
    """
    extent = (bbox.lon_min, bbox.lon_max, bbox.lat_min, bbox.lat_max)
    cropped = hazard.select(extent=extent)
    if cropped is None:
        raise ValueError(f"There is no hazard centroid inside the zone {tuple(bbox)}.")
    return cropped

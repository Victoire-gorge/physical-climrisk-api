"""Shared test fixtures: small synthetic CLIMADA objects, built in memory (no network)."""

import numpy as np
import pytest
from climada.hazard import Centroids, Hazard
from scipy import sparse

# 4 x 4 regular grid around the default zone (lon -1.3..0.35, lat 44.2..45.6):
# only lat 44.5 and 45.0 x lon -1.0 and 0.0 fall inside it, i.e. 4 centroids.
GRID_LATS = np.array([44.0, 44.5, 45.0, 46.0])
GRID_LONS = np.array([-2.0, -1.0, 0.0, 1.0])
FREQUENCIES = np.array([0.5, 0.3, 0.2])


@pytest.fixture
def synthetic_hazard() -> Hazard:
    """River-flood-like hazard: 3 events on a 4 x 4 grid.

    Intensity of event e at centroid c is ``e + c / 100``, so any value can be traced back to
    its event and centroid after a selection.
    """
    lon, lat = np.meshgrid(GRID_LONS, GRID_LATS)
    centroids = Centroids(lat=lat.ravel(), lon=lon.ravel())
    n_events, n_centroids = FREQUENCIES.size, centroids.size
    values = np.arange(n_events)[:, None] + np.arange(n_centroids)[None, :] / 100
    intensity = sparse.csr_matrix(values + 1.0)  # +1 so that no value is a sparse zero
    return Hazard(
        haz_type="RF",
        units="m",
        centroids=centroids,
        event_id=np.arange(1, n_events + 1),
        frequency=FREQUENCIES.copy(),
        event_name=[f"event_{i}" for i in range(1, n_events + 1)],
        date=np.full(n_events, 730000),
        orig=np.ones(n_events, dtype=bool),
        intensity=intensity,
        fraction=sparse.csr_matrix(np.ones_like(values)),
    )

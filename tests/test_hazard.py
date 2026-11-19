"""Tests for cropping a hazard to the configured zone."""

import numpy as np
import pytest
from climada.hazard import Hazard

from climrisk.science.hazard import BBox, crop_hazard

ZONE = BBox(lon_min=-1.3, lat_min=44.2, lon_max=0.35, lat_max=45.6)


def test_crop_keeps_only_centroids_inside_zone(synthetic_hazard: Hazard) -> None:
    cropped = crop_hazard(synthetic_hazard, ZONE)

    assert cropped.centroids.size == 4
    assert set(np.round(cropped.centroids.lat, 6)) == {44.5, 45.0}
    assert set(np.round(cropped.centroids.lon, 6)) == {-1.0, 0.0}


def test_crop_keeps_every_event_and_frequency(synthetic_hazard: Hazard) -> None:
    # Events are kept even when they are zero in the zone: dropping them would not change
    # losses, but it would break the link with the source event set.
    cropped = crop_hazard(synthetic_hazard, ZONE)

    np.testing.assert_array_equal(cropped.event_id, synthetic_hazard.event_id)
    np.testing.assert_allclose(cropped.frequency, synthetic_hazard.frequency)


def test_crop_keeps_intensity_of_selected_centroids(synthetic_hazard: Hazard) -> None:
    cropped = crop_hazard(synthetic_hazard, ZONE)

    in_zone = (
        (synthetic_hazard.centroids.lon >= ZONE.lon_min)
        & (synthetic_hazard.centroids.lon <= ZONE.lon_max)
        & (synthetic_hazard.centroids.lat >= ZONE.lat_min)
        & (synthetic_hazard.centroids.lat <= ZONE.lat_max)
    )
    expected = synthetic_hazard.intensity[:, np.flatnonzero(in_zone)].toarray()
    np.testing.assert_allclose(cropped.intensity.toarray(), expected)


def test_crop_includes_centroids_on_the_boundary(synthetic_hazard: Hazard) -> None:
    zone = BBox(lon_min=-1.0, lat_min=44.5, lon_max=0.0, lat_max=45.0)

    assert crop_hazard(synthetic_hazard, zone).centroids.size == 4


def test_crop_raises_when_zone_has_no_centroid(synthetic_hazard: Hazard) -> None:
    # CLIMADA's select() returns None silently in this case; we fail loudly instead.
    far_away = BBox(lon_min=10.0, lat_min=10.0, lon_max=11.0, lat_max=11.0)

    with pytest.raises(ValueError, match="no hazard centroid"):
        crop_hazard(synthetic_hazard, far_away)


def test_crop_does_not_modify_the_input(synthetic_hazard: Hazard) -> None:
    n_before = synthetic_hazard.centroids.size

    crop_hazard(synthetic_hazard, ZONE)

    assert synthetic_hazard.centroids.size == n_before

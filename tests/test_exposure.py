"""Tests for matching sites to hazard centroids and building CLIMADA exposures."""

import numpy as np
import pandas as pd
import pytest
from climada.entity import Exposures
from climada.hazard import Hazard

from climrisk.science.exposure import nearest_centroid, portfolio_to_exposures
from climrisk.science.vulnerability import AssetType, impact_function_id

KM_PER_DEGREE = 111.195  # great-circle km per degree on CLIMADA's spherical Earth


def centroid_index(hazard: Hazard, lat: float, lon: float) -> int:
    return int(
        np.flatnonzero(
            np.isclose(hazard.centroids.lat, lat) & np.isclose(hazard.centroids.lon, lon)
        )[0]
    )


def test_site_on_a_centroid_matches_it_at_zero_distance(synthetic_hazard: Hazard) -> None:
    match = nearest_centroid(synthetic_hazard, np.array([45.0]), np.array([0.0]))

    assert match.index[0] == centroid_index(synthetic_hazard, 45.0, 0.0)
    assert match.distance_km[0] == pytest.approx(0.0, abs=1e-6)


def test_site_between_centroids_matches_the_nearest(synthetic_hazard: Hazard) -> None:
    # 0.1 degree east of (44.5, -1.0); the next centroid is 0.9 degree away.
    match = nearest_centroid(synthetic_hazard, np.array([44.5]), np.array([-0.9]))

    assert match.index[0] == centroid_index(synthetic_hazard, 44.5, -1.0)
    expected_km = 0.1 * KM_PER_DEGREE * np.cos(np.radians(44.5))
    assert match.distance_km[0] == pytest.approx(expected_km, rel=1e-3)


def test_far_site_is_matched_and_reports_its_distance(synthetic_hazard: Hazard) -> None:
    # No threshold here: deciding what is too far belongs to validation.
    match = nearest_centroid(synthetic_hazard, np.array([43.3]), np.array([5.4]))  # Marseille

    assert match.index[0] >= 0
    assert match.distance_km[0] > 300


def test_matching_is_vectorised_and_keeps_input_order(synthetic_hazard: Hazard) -> None:
    lat = np.array([46.0, 44.0, 45.0])
    lon = np.array([1.0, -2.0, 0.0])

    match = nearest_centroid(synthetic_hazard, lat, lon)

    expected = [centroid_index(synthetic_hazard, la, lo) for la, lo in zip(lat, lon, strict=True)]
    np.testing.assert_array_equal(match.index, expected)


def test_matching_agrees_with_climada_assign_centroids(synthetic_hazard: Hazard) -> None:
    # Guard against a change of behaviour in CLIMADA: our matching must stay the native one.
    rng = np.random.default_rng(42)
    lat = rng.uniform(43.8, 46.2, 500)
    lon = rng.uniform(-2.2, 1.2, 500)
    native = Exposures(lat=lat, lon=lon, value=np.ones_like(lat), crs="EPSG:4326")
    native.assign_centroids(synthetic_hazard, distance="haversine", threshold=np.inf)

    match = nearest_centroid(synthetic_hazard, lat, lon)

    np.testing.assert_array_equal(match.index, native.gdf["centr_RF"].to_numpy())


def test_empty_input_gives_empty_match(synthetic_hazard: Hazard) -> None:
    match = nearest_centroid(synthetic_hazard, np.array([]), np.array([]))

    assert match.index.size == 0
    assert match.distance_km.size == 0


@pytest.fixture
def portfolio() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "site_id": ["plant", "estate_buildings", "estate_vines"],
            "lat": [45.0, 44.5, 44.5],
            "lon": [0.0, -1.0, -1.0],
            "value": [2_000_000.0, 500_000.0, 300_000.0],
            "asset_type": ["industrial", "industrial", "cropland"],
        }
    )


def test_exposures_carry_values_vulnerability_and_centroids(portfolio: pd.DataFrame) -> None:
    exposures = portfolio_to_exposures(portfolio, centroid_index=np.array([10, 5, 5]))
    gdf = exposures.gdf

    assert list(gdf["site_id"]) == ["plant", "estate_buildings", "estate_vines"]
    np.testing.assert_allclose(gdf["value"], portfolio["value"])
    np.testing.assert_allclose(exposures.latitude, portfolio["lat"])
    np.testing.assert_allclose(exposures.longitude, portfolio["lon"])
    assert list(gdf["impf_RF"]) == [
        impact_function_id(AssetType.INDUSTRIAL),
        impact_function_id(AssetType.INDUSTRIAL),
        impact_function_id(AssetType.CROPLAND),
    ]
    assert list(gdf["centr_RF"]) == [10, 5, 5]
    assert exposures.crs.to_epsg() == 4326


def test_two_parts_of_one_estate_share_a_centroid(portfolio: pd.DataFrame) -> None:
    # Buildings and vines at the same place: same hazard, different vulnerability.
    exposures = portfolio_to_exposures(portfolio, centroid_index=np.array([10, 5, 5]))
    gdf = exposures.gdf.set_index("site_id")

    assert gdf.loc["estate_buildings", "centr_RF"] == gdf.loc["estate_vines", "centr_RF"]
    assert gdf.loc["estate_buildings", "impf_RF"] != gdf.loc["estate_vines", "impf_RF"]


@pytest.mark.parametrize(
    "centroid_index",
    [
        np.array([10, -1, 5]),  # CLIMADA's "no match" marker would silently give a zero loss
        np.array([10, 5]),  # one index per site is required
    ],
)
def test_invalid_centroid_index_is_rejected(
    portfolio: pd.DataFrame, centroid_index: np.ndarray
) -> None:
    with pytest.raises(ValueError):
        portfolio_to_exposures(portfolio, centroid_index=centroid_index)

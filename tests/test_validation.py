"""Tests for site validation: grid geometry, distance thresholds and per-site issues."""

import numpy as np
import pandas as pd
import pytest
from climada.hazard import Centroids, Hazard
from scipy import sparse

from climrisk.science.hazard import BBox
from climrisk.science.validation import (
    GridGeometry,
    Issue,
    SiteStatus,
    grid_geometry,
    half_diagonal_km,
    validate_portfolio,
)

# 7 x 7 grid with a 0.5 degree step, whose central 5 x 5 block is missing (a "lake"):
# a half-diagonal is about 34 km there, so the lake centre is far from every centroid.
STEP = 0.5
LATS = 43.5 + STEP * np.arange(7)  # 43.5 .. 46.5
LONS = -2.0 + STEP * np.arange(7)  # -2.0 .. 1.0
LAKE_CENTRE = (45.0, -0.5)  # about 118 km from the nearest centroid: beyond 3 half-diagonals
LAKE_EDGE = (44.0, -1.5)  # about 40 km from (44.0, -2.0): between 1 and 3 half-diagonals


def _hazard(lat: np.ndarray, lon: np.ndarray) -> Hazard:
    """One-event hazard on the given centroids (validation only reads the centroids)."""
    return Hazard(
        haz_type="RF",
        units="m",
        centroids=Centroids(lat=lat, lon=lon),
        event_id=np.array([1]),
        frequency=np.array([1.0]),
        event_name=["event_1"],
        date=np.array([730000]),
        orig=np.array([True]),
        intensity=sparse.csr_matrix(np.ones((1, lat.size))),
        fraction=sparse.csr_matrix(np.ones((1, lat.size))),
    )


def _grid_hazard(lats: np.ndarray, lons: np.ndarray, keep=None) -> Hazard:
    lon, lat = np.meshgrid(lons, lats)
    lat, lon = lat.ravel(), lon.ravel()
    if keep is not None:
        mask = keep(lat, lon)
        lat, lon = lat[mask], lon[mask]
    return _hazard(lat, lon)


@pytest.fixture
def lake_hazard() -> Hazard:
    def outside_lake(lat, lon):
        in_lake = (lat > 43.75) & (lat < 46.25) & (lon > -1.75) & (lon < 0.75)
        return ~in_lake

    return _grid_hazard(LATS, LONS, keep=outside_lake)


def _portfolio(points, **columns) -> pd.DataFrame:
    n = len(points)
    data = {
        "site_id": [f"s{i}" for i in range(n)],
        "lat": [p[0] for p in points],
        "lon": [p[1] for p in points],
        "value": [1000.0] * n,
        "asset_type": ["industrial"] * n,
    }
    data.update(columns)
    return pd.DataFrame(data)


def _validate(hazard: Hazard, portfolio: pd.DataFrame) -> pd.DataFrame:
    return validate_portfolio(portfolio, hazard, grid_geometry(hazard))


# --- grid geometry ---------------------------------------------------------------------------


def test_grid_geometry_reads_step_and_cell_extent(lake_hazard):
    grid = grid_geometry(lake_hazard)
    assert grid.lat_step_deg == pytest.approx(STEP)
    assert grid.lon_step_deg == pytest.approx(STEP)
    # The extent covers whole cells: centroid bounds plus half a step on each side.
    assert grid.extent == pytest.approx(BBox(-2.25, 43.25, 1.25, 46.75))


def test_grid_geometry_accepts_missing_cells(lake_hazard):
    # 24 of 49 cells are missing, but every latitude and longitude still appears.
    assert lake_hazard.centroids.size == 24
    grid_geometry(lake_hazard)


def test_grid_geometry_rejects_shifted_centroid():
    lat = np.array([44.0, 44.0, 44.5, 44.75])
    lon = np.array([0.0, 0.5, 0.0, 0.5])
    with pytest.raises(ValueError, match="regular"):
        grid_geometry(_hazard(lat, lon))


def test_grid_geometry_rejects_missing_interior_row():
    lats = np.array([44.0, 44.5, 45.5])  # 45.0 is missing for every longitude
    with pytest.raises(ValueError, match="regular"):
        grid_geometry(_grid_hazard(lats, LONS))


def test_half_diagonal_of_river_flood_grid_in_gironde():
    step = 1 / 24  # 150 arc seconds, as in the river flood data
    grid = GridGeometry(step, step, BBox(-1.3, 44.2, 0.35, 45.6))
    south, north = half_diagonal_km(grid, np.array([44.2, 45.6]))
    assert south == pytest.approx(2.85, abs=0.01)
    # East-west cell sides shrink with latitude, so does the half-diagonal.
    assert north < south


# --- distance and zone rules -----------------------------------------------------------------


def test_site_on_centroid_is_valid(lake_hazard):
    report = _validate(lake_hazard, _portfolio([(43.5, -2.0)]))
    row = report.iloc[0]
    assert row["status"] == SiteStatus.VALID
    assert row["issues"] == []
    assert row["distance_km"] == pytest.approx(0.0, abs=1e-6)
    assert (row["centroid_lat"], row["centroid_lon"]) == (43.5, -2.0)


def test_site_in_missing_cell_next_to_grid_gets_neighbour_warning(lake_hazard):
    row = _validate(lake_hazard, _portfolio([LAKE_EDGE])).iloc[0]
    assert row["status"] == SiteStatus.WARNING
    assert row["issues"] == [Issue.NEIGHBOUR_CELL]
    assert row["centroid_index"] >= 0


def test_site_far_from_every_centroid_is_excluded_out_of_grid(lake_hazard):
    row = _validate(lake_hazard, _portfolio([LAKE_CENTRE])).iloc[0]
    assert row["status"] == SiteStatus.EXCLUDED
    assert row["issues"] == [Issue.OUT_OF_GRID]


@pytest.mark.parametrize("point", [(43.3, 5.4), (95.0, 0.0), (np.nan, 0.0)])
def test_site_outside_hazard_extent_is_excluded_out_of_zone(lake_hazard, point):
    row = _validate(lake_hazard, _portfolio([point])).iloc[0]
    assert row["status"] == SiteStatus.EXCLUDED
    assert row["issues"] == [Issue.OUT_OF_ZONE]
    # Not matched: CLIMADA's -1 marker, which portfolio_to_exposures refuses.
    assert row["centroid_index"] == -1
    assert np.isnan(row["distance_km"])


def test_random_sites_on_a_complete_grid_are_all_valid():
    # Every site lies inside an existing cell, so none may get a neighbour warning.
    step = 1 / 24
    lats = 44.5 + step * np.arange(10)
    lons = -0.5 + step * np.arange(10)
    hazard = _grid_hazard(lats, lons)
    grid = grid_geometry(hazard)
    rng = np.random.default_rng(0)
    points = list(
        zip(
            rng.uniform(grid.extent.lat_min, grid.extent.lat_max, 2000),
            rng.uniform(grid.extent.lon_min, grid.extent.lon_max, 2000),
            strict=True,
        )
    )
    report = validate_portfolio(_portfolio(points), hazard, grid)
    assert (report["status"] == SiteStatus.VALID).all()


# --- attribute rules -------------------------------------------------------------------------


@pytest.mark.parametrize("value", [0.0, -5.0, np.nan, np.inf])
def test_non_positive_or_non_finite_value_is_excluded(lake_hazard, value):
    row = _validate(lake_hazard, _portfolio([(43.5, -2.0)], value=[value])).iloc[0]
    assert row["status"] == SiteStatus.EXCLUDED
    assert row["issues"] == [Issue.INVALID_VALUE]


def test_unknown_asset_type_is_excluded(lake_hazard):
    row = _validate(lake_hazard, _portfolio([(43.5, -2.0)], asset_type=["castle"])).iloc[0]
    assert row["status"] == SiteStatus.EXCLUDED
    assert row["issues"] == [Issue.UNKNOWN_ASSET_TYPE]


def test_duplicate_site_ids_are_all_excluded(lake_hazard):
    portfolio = _portfolio([(43.5, -2.0), (43.5, -1.5)], site_id=["x", "x"])
    report = _validate(lake_hazard, portfolio)
    assert report["issues"].tolist() == [[Issue.DUPLICATE_SITE_ID]] * 2


def test_two_sites_at_the_same_point_are_valid(lake_hazard):
    # A wine estate: buildings and vines declared as two sites at one location.
    portfolio = _portfolio(
        [(43.5, -2.0), (43.5, -2.0)],
        site_id=["estate_buildings", "estate_vines"],
        asset_type=["industrial", "cropland"],
    )
    report = _validate(lake_hazard, portfolio)
    assert (report["status"] == SiteStatus.VALID).all()


def test_all_issues_of_a_site_are_listed(lake_hazard):
    portfolio = _portfolio([(43.3, 5.4)], value=[-1.0], asset_type=["castle"])
    row = _validate(lake_hazard, portfolio).iloc[0]
    assert set(row["issues"]) == {
        Issue.INVALID_VALUE,
        Issue.UNKNOWN_ASSET_TYPE,
        Issue.OUT_OF_ZONE,
    }


def test_report_follows_portfolio_order(lake_hazard):
    portfolio = _portfolio([LAKE_CENTRE, (43.5, -2.0), LAKE_EDGE], site_id=["c", "a", "b"])
    report = _validate(lake_hazard, portfolio)
    assert report["site_id"].tolist() == ["c", "a", "b"]
    assert report["status"].tolist() == [
        SiteStatus.EXCLUDED,
        SiteStatus.VALID,
        SiteStatus.WARNING,
    ]
    assert report.columns.tolist() == [
        "site_id",
        "status",
        "issues",
        "centroid_index",
        "centroid_lat",
        "centroid_lon",
        "distance_km",
    ]


def test_empty_portfolio_gives_empty_report(lake_hazard):
    report = _validate(lake_hazard, _portfolio([]))
    assert report.empty
    assert "status" in report.columns

"""Tests for impact computation and loss metrics (AAL, PML), on a hand-checkable hazard."""

import numpy as np
import pandas as pd
import pytest
from climada.hazard import Centroids, Hazard
from scipy import sparse

from climrisk.science.exposure import portfolio_to_exposures
from climrisk.science.impact import check_return_periods, compute_impact, risk_metrics

# 10 simulated years, one event per year, each with frequency 1/10.
N_YEARS = 10
CENTROID_LATS = np.array([44.5, 44.5, 45.0])
CENTROID_LONS = np.array([-1.0, 0.0, -1.0])
# Depths in metres, chosen on JRC curve points: industrial damage ratio is 0.27 at 1 m and
# 0.70 at 3 m (see science/vulnerability.py), so every loss can be computed by hand.
# centroid 0: 1 m in year 8, 3 m in year 9; centroid 1: never flooded; centroid 2: 1 m in year 0.
DEPTHS_M = np.zeros((N_YEARS, 3))
DEPTHS_M[8, 0] = 1.0
DEPTHS_M[9, 0] = 3.0
DEPTHS_M[0, 2] = 1.0
VALUE = 1000.0


@pytest.fixture
def yearly_hazard() -> Hazard:
    """River-flood-like hazard of 10 equally likely years on 3 centroids."""
    return Hazard(
        haz_type="RF",
        units="m",
        centroids=Centroids(lat=CENTROID_LATS, lon=CENTROID_LONS),
        event_id=np.arange(1, N_YEARS + 1),
        frequency=np.full(N_YEARS, 1 / N_YEARS),
        event_name=[f"year_{i}" for i in range(N_YEARS)],
        date=np.full(N_YEARS, 730000),
        orig=np.ones(N_YEARS, dtype=bool),
        intensity=sparse.csr_matrix(DEPTHS_M),
        fraction=sparse.csr_matrix((DEPTHS_M > 0).astype(float)),
    )


def _portfolio() -> pd.DataFrame:
    """Site a on centroid 0, site b on centroid 1 (never flooded), site c on centroid 2."""
    return pd.DataFrame(
        {
            "site_id": ["a", "b", "c"],
            "lat": CENTROID_LATS,
            "lon": CENTROID_LONS,
            "value": VALUE,
            "asset_type": ["industrial", "office", "industrial"],
        }
    )


def _metrics(hazard: Hazard, return_periods=(2, 5, 10)):
    portfolio = _portfolio()
    exposures = portfolio_to_exposures(portfolio, np.arange(3))
    impact = compute_impact(exposures, hazard)
    return risk_metrics(impact, portfolio["site_id"], return_periods)


def test_site_aal_is_frequency_weighted_sum_of_losses(yearly_hazard):
    sites = _metrics(yearly_hazard).sites.set_index("site_id")
    # site a loses 270 (year 8) and 700 (year 9); site c loses 270 (year 0).
    assert sites.loc["a", "aal"] == pytest.approx(0.1 * (270 + 700))
    assert sites.loc["c", "aal"] == pytest.approx(0.1 * 270)


def test_portfolio_aal_is_sum_of_site_aal(yearly_hazard):
    metrics = _metrics(yearly_hazard)
    assert metrics.portfolio_aal == pytest.approx(metrics.sites["aal"].sum())


def test_site_pml_is_empirical_loss_of_equally_likely_years(yearly_hazard):
    site_a = _metrics(yearly_hazard).sites.set_index("site_id").loc["a"]
    # 10-year loss: exceeded 1 year in 10, i.e. the largest; 5-year: the second largest.
    assert site_a["pml_10"] == pytest.approx(700)
    assert site_a["pml_5"] == pytest.approx(270)


def test_never_flooded_site_has_zero_metrics_not_nan(yearly_hazard):
    site_b = _metrics(yearly_hazard).sites.set_index("site_id").loc["b"]
    assert site_b[["aal", "pml_2", "pml_5", "pml_10"]].tolist() == [0.0, 0.0, 0.0, 0.0]


def test_return_period_shorter_than_first_loss_gives_zero(yearly_hazard):
    metrics = _metrics(yearly_hazard)
    # Losses happen in 3 years out of 10: a 2-year loss (exceeded 5 years in 10) is zero.
    assert metrics.sites["pml_2"].tolist() == [0.0, 0.0, 0.0]
    assert metrics.portfolio_pml[2] == 0.0


def test_portfolio_pml_uses_yearly_total_not_sum_of_site_pml(yearly_hazard):
    metrics = _metrics(yearly_hazard)
    # Yearly portfolio losses: 270 (year 0), 270 (year 8), 700 (year 9).
    assert metrics.portfolio_pml[10] == pytest.approx(700)
    assert metrics.portfolio_pml[5] == pytest.approx(270)
    # Sites a and c are flooded in different years, so their 10-year losses do not add up.
    assert metrics.sites["pml_10"].sum() == pytest.approx(700 + 270)


def test_compute_impact_keeps_the_given_centroids(yearly_hazard):
    portfolio = _portfolio().iloc[[0]]
    # Site a lies on centroid 0, but is forced onto centroid 1 (never flooded).
    exposures = portfolio_to_exposures(portfolio, np.array([1]))
    impact = compute_impact(exposures, yearly_hazard)
    assert impact.aai_agg == 0.0


def test_site_order_and_ids_follow_the_portfolio(yearly_hazard):
    sites = _metrics(yearly_hazard).sites
    assert sites["site_id"].tolist() == ["a", "b", "c"]
    assert sites.columns.tolist() == ["site_id", "aal", "pml_2", "pml_5", "pml_10"]


def test_check_return_periods_accepts_periods_within_simulated_years(yearly_hazard):
    check_return_periods(yearly_hazard, (2, 5, 10))


def test_check_return_periods_rejects_periods_longer_than_simulated_years(yearly_hazard):
    with pytest.raises(ValueError, match="20"):
        check_return_periods(yearly_hazard, (5, 20))

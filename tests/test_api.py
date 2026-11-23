"""Tests for the HTTP API, on a small hazard file written to a temporary directory."""

import numpy as np
import pytest
from climada.hazard import Centroids, Hazard
from fastapi.testclient import TestClient
from scipy import sparse

from climrisk.api.app import create_app
from climrisk.api.schemas import MAX_SITES
from climrisk.config import Settings
from climrisk.science.impact import RETURN_PERIODS_YEARS
from climrisk.science.vulnerability import AssetType

# Equally likely simulated years: at least 250 for the 250-year return period, and not 250
# itself, where N / T is a whole number and float rounding picks between two ranks.
N_YEARS = 260
# Regular grid (0.5 x 1 degree) with one missing cell at (45.0, 0.0).
CENTROID_LATS = np.array([44.5, 44.5, 45.0])
CENTROID_LONS = np.array([-1.0, 0.0, -1.0])
# Centroid 0 is flooded 1 m in year 0 and 3 m in year 1; the others never.
# Industrial damage ratio: 0.27 at 1 m, 0.70 at 3 m (JRC Europe).
DEPTHS_M = np.zeros((N_YEARS, 3))
DEPTHS_M[0, 0] = 1.0
DEPTHS_M[1, 0] = 3.0

ON_FLOODED = {"lat": 44.5, "lon": -1.0}
ON_DRY = {"lat": 44.5, "lon": 0.0}
IN_MISSING_CELL = {"lat": 45.0, "lon": 0.0}  # nearest centroid is 1.2 half-diagonals away
MARSEILLE = {"lat": 43.3, "lon": 5.4}  # outside the hazard extent


def _site(site_id: str, point: dict, value=1000.0, asset_type="industrial") -> dict:
    return {"site_id": site_id, **point, "value": value, "asset_type": asset_type}


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Settings pointing to a temporary data directory holding a synthetic hazard file."""
    settings = Settings(_env_file=None, data_dir=tmp_path)
    hazard = Hazard(
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
    settings.hazard_file.parent.mkdir(parents=True)
    hazard.write_hdf5(settings.hazard_file)
    return settings


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:  # "with" runs the startup
        yield client


def _by_id(sites: list[dict]) -> dict[str, dict]:
    return {site["site_id"]: site for site in sites}


# --- startup and description -----------------------------------------------------------------


def test_startup_fails_clearly_without_hazard_file(tmp_path):
    app = create_app(Settings(_env_file=None, data_dir=tmp_path))
    with pytest.raises(FileNotFoundError, match="climrisk.prepare"):
        with TestClient(app):
            pass


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_hazards_describe_the_loaded_hazard(client):
    (hazard,) = client.get("/v1/hazards").json()
    assert hazard["hazard_type"] == "river_flood"
    assert hazard["intensity_unit"] == "m"
    assert hazard["simulated_years"] == pytest.approx(N_YEARS)
    assert hazard["grid"] == {"lat_step_deg": 0.5, "lon_step_deg": 1.0}
    assert hazard["extent"] == pytest.approx(
        {"lon_min": -1.5, "lat_min": 44.25, "lon_max": 0.5, "lat_max": 45.25}
    )
    assert hazard["return_periods_years"] == list(RETURN_PERIODS_YEARS)
    assert hazard["asset_types"] == [t.value for t in AssetType]


# --- validate --------------------------------------------------------------------------------


def test_validate_reports_each_site_in_order(client):
    sites = [
        _site("marseille", MARSEILLE),
        _site("flooded", ON_FLOODED),
        _site("missing_cell", IN_MISSING_CELL),
    ]
    body = client.post("/v1/validate", json={"sites": sites}).json()
    assert [s["site_id"] for s in body["sites"]] == ["marseille", "flooded", "missing_cell"]
    report = _by_id(body["sites"])
    assert report["flooded"]["status"] == "valid"
    assert report["flooded"]["issues"] == []
    assert report["flooded"]["matched_centroid"] == pytest.approx(
        {"lat": 44.5, "lon": -1.0, "distance_km": 0.0}, abs=1e-6
    )
    assert report["missing_cell"]["status"] == "warning"
    assert report["missing_cell"]["issues"] == ["neighbour_cell"]
    assert report["marseille"]["status"] == "excluded"
    assert report["marseille"]["issues"] == ["out_of_zone"]
    assert report["marseille"]["matched_centroid"] is None
    assert body["counts"] == {"valid": 1, "warning": 1, "excluded": 1}


@pytest.mark.parametrize(
    "site",
    [
        {"site_id": "a", "lat": 44.5, "value": 1000.0, "asset_type": "office"},  # no lon
        _site("a", ON_FLOODED, value="a lot"),
    ],
)
def test_malformed_request_is_rejected_as_a_whole(client, site):
    response = client.post("/v1/validate", json={"sites": [site, _site("b", ON_DRY)]})
    assert response.status_code == 422


def test_unknown_asset_type_excludes_the_site_not_the_request(client):
    sites = [_site("castle", ON_FLOODED, asset_type="castle"), _site("b", ON_DRY)]
    response = client.post("/v1/validate", json={"sites": sites})
    assert response.status_code == 200
    report = _by_id(response.json()["sites"])
    assert report["castle"]["issues"] == ["unknown_asset_type"]
    assert report["b"]["status"] == "valid"


@pytest.mark.parametrize("n_sites", [0, MAX_SITES + 1])
def test_empty_or_too_large_portfolio_is_rejected(client, n_sites):
    sites = [_site(f"s{i}", ON_DRY) for i in range(n_sites)]
    assert client.post("/v1/validate", json={"sites": sites}).status_code == 422


# --- analyze ---------------------------------------------------------------------------------


def test_analyze_returns_hand_checked_metrics(client):
    body = client.post("/v1/analyze", json={"sites": [_site("flooded", ON_FLOODED)]}).json()
    metrics = body["sites"][0]["metrics"]
    # Losses: 270 in year 0, 700 in year 1, each with frequency 1/260.
    assert metrics["aal"] == pytest.approx((270 + 700) / N_YEARS)
    pml = {p["return_period_years"]: p["loss"] for p in metrics["pml"]}
    # The T-year loss is the loss of rank floor(260 / T) + 1. 250 years: rank 2 (270).
    # 100 years: rank 3, i.e. 0, since a loss occurs only once every 130 years on average.
    assert pml == pytest.approx({10: 0.0, 50: 0.0, 100: 0.0, 250: 270.0})
    assert body["value_unit"] == "EUR"


def test_analyze_excludes_invalid_sites_from_portfolio_totals(client):
    sites = [
        _site("flooded", ON_FLOODED),
        _site("dry", ON_DRY, asset_type="office"),
        _site("negative", ON_FLOODED, value=-1.0),
    ]
    body = client.post("/v1/analyze", json={"sites": sites}).json()
    report = _by_id(body["sites"])
    assert report["negative"]["status"] == "excluded"
    assert report["negative"]["metrics"] is None
    assert report["dry"]["metrics"]["aal"] == 0.0
    # The negative site sits on the flooded centroid, but must not add to the totals.
    assert body["portfolio"]["aal"] == pytest.approx(report["flooded"]["metrics"]["aal"])
    assert body["counts"] == {"valid": 2, "warning": 0, "excluded": 1}


def test_analyze_portfolio_never_flooded_returns_zero_metrics(client):
    response = client.post("/v1/analyze", json={"sites": [_site("dry", ON_DRY)]})
    assert response.status_code == 200
    portfolio = response.json()["portfolio"]
    assert portfolio["aal"] == 0.0
    assert [p["loss"] for p in portfolio["pml"]] == [0.0] * len(RETURN_PERIODS_YEARS)


def test_analyze_with_every_site_excluded_returns_422_with_report(client):
    sites = [_site("marseille", MARSEILLE), _site("castle", ON_DRY, asset_type="castle")]
    response = client.post("/v1/analyze", json={"sites": sites})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert [s["site_id"] for s in detail["sites"]] == ["marseille", "castle"]
    assert detail["sites"][0]["issues"] == ["out_of_zone"]


def test_validate_and_analyze_agree_on_every_site(client):
    sites = [
        _site("flooded", ON_FLOODED),
        _site("missing_cell", IN_MISSING_CELL),
        _site("marseille", MARSEILLE),
        _site("dup", ON_DRY),
        _site("dup", ON_DRY),
    ]
    fields = ("site_id", "status", "issues", "matched_centroid")
    validated = client.post("/v1/validate", json={"sites": sites}).json()["sites"]
    analyzed = client.post("/v1/analyze", json={"sites": sites}).json()["sites"]
    assert [{k: s[k] for k in fields} for s in analyzed] == validated

"""FastAPI application: loads the hazard once at startup, then validates and analyses portfolios.

Run with ``uvicorn --factory climrisk.api.app:create_app``. See docs/decisions/007-api-contract.md.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import NamedTuple

import pandas as pd
from climada.hazard import Hazard
from fastapi import APIRouter, FastAPI, HTTPException, Request

from climrisk import __version__
from climrisk.api.schemas import (
    AnalysisResponse,
    Extent,
    GridStep,
    HazardInfo,
    LossMetrics,
    MatchedCentroid,
    Portfolio,
    ReturnPeriodLoss,
    SiteAnalysis,
    SiteValidation,
    ValidationResponse,
)
from climrisk.config import Settings
from climrisk.science.exposure import VALUE_UNIT, portfolio_to_exposures
from climrisk.science.impact import (
    RETURN_PERIODS_YEARS,
    check_return_periods,
    compute_impact,
    risk_metrics,
)
from climrisk.science.validation import (
    GridGeometry,
    SiteStatus,
    grid_geometry,
    validate_portfolio,
)
from climrisk.science.vulnerability import HAZARD_TYPE, AssetType


class Service(NamedTuple):
    """Everything loaded at startup and shared, read-only, by all requests."""

    settings: Settings
    hazard: Hazard
    grid: GridGeometry


def load_service(settings: Settings) -> Service:
    """Read the prepared hazard file and check it can serve requests.

    Raises:
        FileNotFoundError: if the hazard file has not been prepared.
        ValueError: if the hazard is of another type, its grid is irregular, or it simulates
            fewer years than the longest return period.
    """
    path = settings.hazard_file
    if not path.is_file():
        raise FileNotFoundError(
            f"Hazard file {path} not found: run `python -m climrisk.prepare` first."
        )
    hazard = Hazard.from_hdf5(path)
    if hazard.haz_type != HAZARD_TYPE:
        raise ValueError(f"Expected a {HAZARD_TYPE} hazard in {path}, got {hazard.haz_type}.")
    grid = grid_geometry(hazard)
    check_return_periods(hazard, RETURN_PERIODS_YEARS)
    return Service(settings=settings, hazard=hazard, grid=grid)


router = APIRouter()


# Routes are plain ``def``: FastAPI runs them in a thread pool, so a CPU-bound CLIMADA
# computation does not block the event loop and the other requests.


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness check for a load balancer: the service only starts once the hazard is loaded."""
    return {"status": "ok"}


@router.get("/v1/hazards")
def hazards(request: Request) -> list[HazardInfo]:
    """Describe the loaded hazard: zone extent, grid step, return periods, asset types."""
    service: Service = request.app.state.service
    settings, hazard, grid = service
    return [
        HazardInfo(
            hazard_type=settings.hazard_type,
            intensity_unit=hazard.units,
            scenario=settings.hazard_scenario,
            year_range=settings.hazard_year_range,
            simulated_years=1 / float(hazard.frequency.min()),
            extent=Extent(**grid.extent._asdict()),
            grid=GridStep(lat_step_deg=grid.lat_step_deg, lon_step_deg=grid.lon_step_deg),
            return_periods_years=list(RETURN_PERIODS_YEARS),
            asset_types=list(AssetType),
        )
    ]


@router.post("/v1/validate")
def validate(portfolio: Portfolio, request: Request) -> ValidationResponse:
    """Check every site and report its status, issues and matched hazard centroid."""
    service: Service = request.app.state.service
    report = validate_portfolio(_to_frame(portfolio), service.hazard, service.grid)
    return ValidationResponse(counts=_counts(report), sites=_site_validations(report))


@router.post("/v1/analyze")
def analyze(portfolio: Portfolio, request: Request) -> AnalysisResponse:
    """Validate the sites, then compute AAL and PML of every site that is not excluded.

    Answers 422, with the validation report, when every site is excluded.
    """
    service: Service = request.app.state.service
    sites = _to_frame(portfolio)
    report = validate_portfolio(sites, service.hazard, service.grid)
    validations = _site_validations(report)
    evaluated = (report["status"] != SiteStatus.EXCLUDED).to_numpy()
    if not evaluated.any():
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Every site is excluded, see the issues of each site.",
                "sites": [v.model_dump(mode="json") for v in validations],
            },
        )

    exposures = portfolio_to_exposures(
        sites[evaluated], report["centroid_index"].to_numpy()[evaluated]
    )
    metrics = risk_metrics(compute_impact(exposures, service.hazard), sites["site_id"][evaluated])
    site_metrics = iter(metrics.sites.to_dict("records"))  # evaluated sites, in order
    results = [
        SiteAnalysis(
            **validation.model_dump(),
            metrics=_loss_metrics(next(site_metrics)) if is_evaluated else None,
        )
        for validation, is_evaluated in zip(validations, evaluated, strict=True)
    ]
    portfolio_metrics = LossMetrics(
        aal=metrics.portfolio_aal,
        pml=[
            ReturnPeriodLoss(return_period_years=rp, loss=loss)
            for rp, loss in metrics.portfolio_pml.items()
        ],
    )
    return AnalysisResponse(
        value_unit=VALUE_UNIT, counts=_counts(report), portfolio=portfolio_metrics, sites=results
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. The hazard is loaded at startup, never in a request."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.service = load_service(settings or Settings())
        yield

    app = FastAPI(title="climrisk", version=__version__, lifespan=lifespan)
    app.include_router(router)
    return app


def _to_frame(portfolio: Portfolio) -> pd.DataFrame:
    return pd.DataFrame(
        [site.model_dump() for site in portfolio.sites],
        columns=["site_id", "lat", "lon", "value", "asset_type"],
    )


def _counts(report: pd.DataFrame) -> dict[SiteStatus, int]:
    observed = report["status"].value_counts()
    return {status: int(observed.get(status, 0)) for status in SiteStatus}


def _site_validations(report: pd.DataFrame) -> list[SiteValidation]:
    return [
        SiteValidation(
            site_id=row.site_id,
            status=row.status,
            issues=row.issues,
            matched_centroid=None
            if row.centroid_index < 0
            else MatchedCentroid(
                lat=row.centroid_lat, lon=row.centroid_lon, distance_km=row.distance_km
            ),
        )
        for row in report.itertuples(index=False)
    ]


def _loss_metrics(site: dict) -> LossMetrics:
    return LossMetrics(
        aal=site["aal"],
        pml=[
            ReturnPeriodLoss(return_period_years=rp, loss=site[f"pml_{rp}"])
            for rp in RETURN_PERIODS_YEARS
        ],
    )

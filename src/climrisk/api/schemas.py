"""Request and response models of the HTTP API.

These models check only the shape of a request (fields, types, portfolio size). Business rules
(positive value, known asset type, zone, distance) live in ``climrisk.science.validation`` and
are reported site by site. See docs/decisions/006 and 007.
"""

from pydantic import BaseModel, Field

from climrisk.science.exposure import VALUE_UNIT
from climrisk.science.validation import Issue, SiteStatus
from climrisk.science.vulnerability import AssetType

# Measured on the Gironde hazard (see docs/decisions/007): 10,000 random sites are analysed in
# 0.56 s with a 3.5 MB response (1.2 MB request) and a 490 MB process peak. That stays under the
# 6 MB AWS Lambda limit for a synchronous response, with room for longer site ids.
MAX_SITES = 10_000


class Site(BaseModel):
    """One location and its asset."""

    site_id: str = Field(min_length=1, description="Client identifier, unique in the portfolio.")
    lat: float = Field(description="Latitude in degrees (EPSG:4326).")
    lon: float = Field(description="Longitude in degrees (EPSG:4326).")
    value: float = Field(description=f"Asset value in {VALUE_UNIT}, strictly positive.")
    asset_type: str = Field(
        description="One of: " + ", ".join(t.value for t in AssetType) + ". "
        "An unknown type excludes the site instead of rejecting the request.",
    )


class Portfolio(BaseModel):
    """The set of sites submitted by a client."""

    sites: list[Site] = Field(min_length=1, max_length=MAX_SITES)


class MatchedCentroid(BaseModel):
    """Hazard centroid used for a site, and the distance between them."""

    lat: float
    lon: float
    distance_km: float


class SiteValidation(BaseModel):
    """Validation outcome of one site."""

    site_id: str
    status: SiteStatus
    issues: list[Issue]
    matched_centroid: MatchedCentroid | None = Field(
        description="Null when the site is out of zone."
    )


class ValidationResponse(BaseModel):
    """Per-site validation report, in portfolio order."""

    counts: dict[SiteStatus, int]
    sites: list[SiteValidation]


class ReturnPeriodLoss(BaseModel):
    """Probable maximum loss at one return period."""

    return_period_years: int
    loss: float


class LossMetrics(BaseModel):
    """Average annual loss and probable maximum losses, in the value unit."""

    aal: float
    pml: list[ReturnPeriodLoss]


class SiteAnalysis(SiteValidation):
    """Validation outcome and loss metrics of one site."""

    metrics: LossMetrics | None = Field(description="Null when the site is excluded.")


class AnalysisResponse(BaseModel):
    """Loss metrics of every evaluated site and of the portfolio they form."""

    value_unit: str
    counts: dict[SiteStatus, int]
    portfolio: LossMetrics = Field(description="Computed on evaluated sites only.")
    sites: list[SiteAnalysis]


class Extent(BaseModel):
    """Area covered by the hazard cells, in degrees (EPSG:4326)."""

    lon_min: float
    lat_min: float
    lon_max: float
    lat_max: float


class GridStep(BaseModel):
    """Size of a hazard grid cell, in degrees."""

    lat_step_deg: float
    lon_step_deg: float


class HazardInfo(BaseModel):
    """Description of a loaded hazard."""

    hazard_type: str
    intensity_unit: str
    scenario: str
    year_range: str
    simulated_years: float
    extent: Extent
    grid: GridStep
    return_periods_years: list[int]
    asset_types: list[AssetType]

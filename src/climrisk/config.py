"""Service settings, read from ``CLIMRISK_*`` environment variables or a .env file."""

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from climrisk.science.hazard import BBox

# Guard rail before any download. Measured on the CLIMADA data API: river_flood files for France
# weigh 2.9 to 5.7 MB, whereas the 4.4 km windstorm file (WISC) for France weighs 2,738 MB and
# needs a dedicated extraction step. 50 MB lets the first kind through and stops the second.
DEFAULT_MAX_DOWNLOAD_MB = 50.0


class Settings(BaseSettings):
    """Deployment settings. The zone is a parameter, never a constant in the code."""

    model_config = SettingsConfigDict(env_prefix="CLIMRISK_", env_file=".env", extra="ignore")

    hazard_type: str = "river_flood"
    hazard_country: str = "FRA"
    hazard_scenario: str = "historical"
    hazard_year_range: str = "1980_2000"
    # Gironde (France): lon_min, lat_min, lon_max, lat_max. See docs/decisions/002.
    zone_bbox: BBox = BBox(-1.3, 44.2, 0.35, 45.6)
    data_dir: Path = Path("data")
    max_download_mb: float = DEFAULT_MAX_DOWNLOAD_MB

    @field_validator("zone_bbox")
    @classmethod
    def _check_bbox(cls, bbox: BBox) -> BBox:
        if not (-180 <= bbox.lon_min < bbox.lon_max <= 180):
            raise ValueError("zone_bbox needs -180 <= lon_min < lon_max <= 180")
        if not (-90 <= bbox.lat_min < bbox.lat_max <= 90):
            raise ValueError("zone_bbox needs -90 <= lat_min < lat_max <= 90")
        return bbox

    @property
    def hazard_properties(self) -> dict[str, str]:
        """Dataset properties used to query the CLIMADA data API."""
        return {
            "country_iso3alpha": self.hazard_country,
            "climate_scenario": self.hazard_scenario,
            "year_range": self.hazard_year_range,
        }

    @property
    def hazard_file(self) -> Path:
        """Local file holding the hazard cropped to the zone.

        The zone is part of the name, so changing the zone can never reuse a stale file.
        """
        zone = "_".join(f"{v:g}" for v in self.zone_bbox)
        name = (
            f"{self.hazard_type}_{self.hazard_country}_{self.hazard_scenario}_"
            f"{self.hazard_year_range}_zone_{zone}.hdf5"
        )
        return self.data_dir / "hazard" / name

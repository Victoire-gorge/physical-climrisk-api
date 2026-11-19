"""Tests for settings read from environment variables."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from climrisk.config import Settings
from climrisk.science.hazard import BBox


def test_defaults_describe_the_v1_zone() -> None:
    settings = Settings(_env_file=None)

    assert settings.zone_bbox == BBox(-1.3, 44.2, 0.35, 45.6)
    assert settings.hazard_properties == {
        "country_iso3alpha": "FRA",
        "climate_scenario": "historical",
        "year_range": "1980_2000",
    }


def test_zone_can_be_set_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIMRISK_ZONE_BBOX", "[0.0, 49.0, 1.5, 49.8]")

    assert Settings(_env_file=None).zone_bbox == BBox(0.0, 49.0, 1.5, 49.8)


@pytest.mark.parametrize(
    "bbox",
    [
        (1.0, 44.0, 0.0, 45.0),  # lon_min > lon_max
        (0.0, 45.0, 1.0, 44.0),  # lat_min > lat_max
        (0.0, 44.0, 0.0, 45.0),  # empty width
        (-181.0, 44.0, 0.0, 45.0),  # longitude out of range
        (0.0, -91.0, 1.0, 45.0),  # latitude out of range
    ],
)
def test_invalid_zone_is_rejected(bbox: tuple[float, float, float, float]) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, zone_bbox=bbox)


def test_hazard_file_name_changes_with_the_zone(tmp_path: Path) -> None:
    # A file prepared for another zone must never be picked up silently.
    a = Settings(_env_file=None, data_dir=tmp_path)
    b = Settings(_env_file=None, data_dir=tmp_path, zone_bbox=(0.0, 49.0, 1.5, 49.8))

    assert a.hazard_file != b.hazard_file
    assert a.hazard_file.parent == tmp_path / "hazard"

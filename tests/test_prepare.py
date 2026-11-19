"""Tests for the hazard preparation command, with a fake data API client (no network)."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from climada.hazard import Hazard

from climrisk.config import Settings
from climrisk.prepare import DownloadTooLargeError, prepare_hazard


class FakeClient:
    """Stands in for climada.util.api_client.Client and records what it is asked."""

    def __init__(self, hazard: Hazard, size_mb: float = 4.0) -> None:
        self.hazard = hazard
        self.info = SimpleNamespace(
            name="fake_river_flood", files=[SimpleNamespace(file_size=size_mb * 1e6)]
        )
        self.queries: list[dict] = []
        self.downloads = 0

    def get_dataset_info(self, **query):
        self.queries.append(query)
        return self.info

    def to_hazard(self, dataset):
        self.downloads += 1
        return self.hazard


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path)


def test_writes_hazard_cropped_to_zone(synthetic_hazard: Hazard, settings: Settings) -> None:
    client = FakeClient(synthetic_hazard)

    path = prepare_hazard(settings, client)

    assert path == settings.hazard_file
    assert Hazard.from_hdf5(path).centroids.size == 4
    assert client.queries == [
        {
            "data_type": "river_flood",
            "properties": settings.hazard_properties,
            "status": "active",
        }
    ]


def test_second_run_does_not_download_again(synthetic_hazard: Hazard, settings: Settings) -> None:
    client = FakeClient(synthetic_hazard)

    prepare_hazard(settings, client)
    prepare_hazard(settings, client)

    assert client.downloads == 1


def test_force_downloads_again(synthetic_hazard: Hazard, settings: Settings) -> None:
    client = FakeClient(synthetic_hazard)

    prepare_hazard(settings, client)
    prepare_hazard(settings, client, force=True)

    assert client.downloads == 2


def test_refuses_dataset_above_size_cap(synthetic_hazard: Hazard, settings: Settings) -> None:
    client = FakeClient(synthetic_hazard, size_mb=2738.0)

    with pytest.raises(DownloadTooLargeError, match="2738"):
        prepare_hazard(settings, client)

    assert client.downloads == 0
    assert not settings.hazard_file.exists()


def test_dry_run_neither_downloads_nor_writes(synthetic_hazard: Hazard, settings: Settings) -> None:
    client = FakeClient(synthetic_hazard)

    prepare_hazard(settings, client, dry_run=True)

    assert client.downloads == 0
    assert not settings.hazard_file.exists()


def test_failed_crop_leaves_no_file(synthetic_hazard: Hazard, tmp_path: Path) -> None:
    # Zone without any centroid: the run fails and must not leave a partial or empty file.
    settings = Settings(_env_file=None, data_dir=tmp_path, zone_bbox=(10.0, 10.0, 11.0, 11.0))

    with pytest.raises(ValueError):
        prepare_hazard(settings, FakeClient(synthetic_hazard))

    assert list(tmp_path.rglob("*.hdf5*")) == []

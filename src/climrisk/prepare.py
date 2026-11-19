"""Prepare the hazard file for the configured zone: download, crop, write.

Run once before starting the API (the API never downloads anything)::

    python -m climrisk.prepare [--dry-run] [--force]
"""

import argparse
import logging
from pathlib import Path
from typing import Any

from climrisk.config import Settings
from climrisk.science.hazard import crop_hazard

# Explicit name: under `python -m`, __name__ is "__main__", which hides the source in the logs.
logger = logging.getLogger("climrisk.prepare")


class DownloadTooLargeError(RuntimeError):
    """The requested dataset exceeds the configured download cap."""


def prepare_hazard(
    settings: Settings, client: Any, *, force: bool = False, dry_run: bool = False
) -> Path:
    """Download the configured hazard, crop it to the zone and write it to ``settings.hazard_file``.

    Idempotent: if the file already exists, nothing is downloaded unless ``force`` is set.
    The file is written under a temporary name and renamed only once complete, so an
    interrupted run never leaves a file that looks valid.

    Args:
        settings: deployment settings (dataset query, zone, data directory, size cap).
        client: a ``climada.util.api_client.Client`` (injected so tests can pass a fake).
        force: download and rewrite even if the file exists.
        dry_run: query the dataset and check its size, but download and write nothing.

    Raises:
        DownloadTooLargeError: if the dataset is larger than ``settings.max_download_mb``.
        ValueError: if the zone contains no hazard centroid.
    """
    target = settings.hazard_file
    if target.exists() and not force:
        logger.info("Hazard file already prepared, skipping: %s", target)
        return target

    info = client.get_dataset_info(
        data_type=settings.hazard_type, properties=settings.hazard_properties, status="active"
    )
    size_mb = sum(f.file_size for f in info.files) / 1e6
    logger.info("Dataset %s: %.1f MB", info.name, size_mb)
    if size_mb > settings.max_download_mb:
        raise DownloadTooLargeError(
            f"Dataset {info.name} is {size_mb:.0f} MB, above the cap of "
            f"{settings.max_download_mb:g} MB (CLIMRISK_MAX_DOWNLOAD_MB)."
        )
    if dry_run:
        logger.info("Dry run: would write %s", target)
        return target

    hazard = crop_hazard(client.to_hazard(info), settings.zone_bbox)
    logger.info(
        "Cropped to zone %s: %d centroids, %d events",
        tuple(settings.zone_bbox),
        hazard.centroids.size,
        hazard.size,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    hazard.write_hdf5(partial)
    partial.replace(target)  # atomic on the same file system: write first, then mark as done
    logger.info("Wrote %s", target)
    return target


def main() -> None:
    """Command line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="rewrite even if the file exists")
    parser.add_argument("--dry-run", action="store_true", help="check the dataset, write nothing")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    from climada.util.api_client import Client  # imported here: only the CLI needs the network

    prepare_hazard(Settings(), Client(), force=args.force, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

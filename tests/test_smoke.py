"""Smoke test: the package is installed and exposes its version."""

import climrisk


def test_version_is_exposed() -> None:
    assert climrisk.__version__ == "0.1.0"

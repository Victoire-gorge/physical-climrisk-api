"""Pure functions of the web interface: geometry, insurance formulas and response formatting.

No Streamlit and no network here, so these functions are tested offline. The interface only
knows the API through its JSON responses: it never imports the ``climrisk`` package.
"""

import io
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

# RGBA colours of each validation status on the map.
STATUS_COLORS: dict[str, list[int]] = {
    "valid": [46, 160, 67, 220],
    "warning": [230, 140, 20, 230],
    "excluded": [210, 50, 50, 230],
}


# Opacity of a status colour as a table background: light enough to read black text on it.
TABLE_ROW_OPACITY = 0.25


def status_css(status: str) -> str:
    """CSS background of a table row, in the same colour as the site on the map."""
    red, green, blue, _ = STATUS_COLORS[status]
    return f"background-color: rgba({red}, {green}, {blue}, {TABLE_ROW_OPACITY})"


def cell_polygon(lat: float, lon: float, lat_step: float, lon_step: float) -> list[list[float]]:
    """Corners ``[lon, lat]`` of the grid cell centred on a hazard centroid."""
    half_lat, half_lon = lat_step / 2, lon_step / 2
    return [
        [lon - half_lon, lat - half_lat],
        [lon + half_lon, lat - half_lat],
        [lon + half_lon, lat + half_lat],
        [lon - half_lon, lat + half_lat],
    ]


def extent_polygon(extent: dict[str, float]) -> list[list[float]]:
    """Corners ``[lon, lat]`` of the zone extent returned by ``GET /v1/hazards``."""
    return [
        [extent["lon_min"], extent["lat_min"]],
        [extent["lon_max"], extent["lat_min"]],
        [extent["lon_max"], extent["lat_max"]],
        [extent["lon_min"], extent["lat_max"]],
    ]


REQUIRED_COLUMNS = ("site_id", "lat", "lon", "value", "asset_type")
OPTIONAL_COLUMNS = ("description",)
NUMERIC_COLUMNS = ("lat", "lon", "value")


def parse_portfolio_file(name: str, content: bytes) -> list[dict]:
    """Read an uploaded portfolio (CSV or JSON) into one dict per site.

    CSV: one row per site with the required columns, ``description`` optional. Files exported by
    a French Excel (``;`` between columns, ``,`` as decimal mark) are accepted. JSON: the API
    request format ``{"sites": [...]}`` or a plain list of sites.

    Only the file structure is checked here. Site values are checked by the API, which reports
    them site by site.

    Raises:
        ValueError: with a message for the user, if the file cannot be read as a portfolio.
    """
    suffix = Path(name).suffix.lower()
    if suffix == ".csv":
        text = content.decode("utf-8-sig")  # the BOM Excel adds is skipped
        header = text.splitlines()[0] if text else ""
        french = header.count(";") > header.count(",")
        frame = pd.read_csv(io.StringIO(text), sep=";" if french else ",", dtype=str)
        frame.columns = [column.strip() for column in frame.columns]
        if french:
            for column in set(NUMERIC_COLUMNS) & set(frame.columns):
                frame[column] = frame[column].str.replace(",", ".", regex=False)
    elif suffix == ".json":
        try:
            data = json.loads(content)
        except json.JSONDecodeError as error:
            raise ValueError(f"The file is not valid JSON: {error}.") from error
        sites = data.get("sites") if isinstance(data, dict) else data
        if not isinstance(sites, list):
            raise ValueError('A JSON portfolio is a list of sites, or {"sites": [...]}.')
        frame = pd.DataFrame(sites)
    else:
        raise ValueError(f"Unsupported file type '{suffix}': use a .csv or .json file.")

    missing = sorted(set(REQUIRED_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(
            f"Missing columns: {', '.join(missing)}. "
            f"Expected: {', '.join(REQUIRED_COLUMNS)}, and optionally description."
        )
    for column in OPTIONAL_COLUMNS:
        if column not in frame.columns:
            frame[column] = None
    for column in NUMERIC_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype(float)
    frame = frame[list(REQUIRED_COLUMNS + OPTIONAL_COLUMNS)]
    return frame.astype(object).where(frame.notna(), None).to_dict("records")


def portfolio_summary(sites: list[dict]) -> dict:
    """Number of sites, total value and value per asset type of a portfolio being edited.

    Rows still being typed (empty or non-numeric value, empty type) count as sites but add no
    value, so the summary never fails while a user edits the table.
    """
    total, by_type = 0.0, {}
    for site in sites:
        value, asset_type = site.get("value"), site.get("asset_type")
        if not isinstance(value, int | float) or not math.isfinite(value) or not asset_type:
            continue
        total += value
        by_type[asset_type] = by_type.get(asset_type, 0.0) + value
    return {"n_sites": len(sites), "total_value": total, "value_by_asset_type": by_type}


def probability_at_least_one(return_period_years: float, years: int) -> float:
    """Chance of at least one event of a given return period over ``years`` years.

    A T-year event has a 1/T chance every year, independently: over n years the chance of at
    least one is 1 - (1 - 1/T)^n, e.g. 26 % for a 100-year flood over 30 years.
    """
    return 1 - (1 - 1 / return_period_years) ** years


def damage_ratio(curve: dict, depth_m: float) -> float:
    """Damage ratio at ``depth_m``, interpolated linearly as CLIMADA does between curve points."""
    return float(np.interp(depth_m, curve["depths_m"], curve["damage_ratios"]))


def _pml_by_return_period(metrics: dict) -> dict[int, float]:
    return {p["return_period_years"]: p["loss"] for p in metrics["pml"]}


def result_rows(analysis: dict) -> list[dict]:
    """One flat row per site of an ``/v1/analyze`` response, for a table.

    Excluded sites keep their row, with ``None`` metrics, so the table shows why they are missing.
    """
    return_periods = [p["return_period_years"] for p in analysis["portfolio"]["pml"]]
    rows = []
    for site in analysis["sites"]:
        centroid, metrics = site["matched_centroid"], site["metrics"]
        pml = _pml_by_return_period(metrics) if metrics else {}
        row = {
            "site_id": site["site_id"],
            "status": site["status"],
            "issues": ", ".join(site["issues"]),
            "distance_km": centroid["distance_km"] if centroid else None,
            "aal": metrics["aal"] if metrics else None,
        }
        row.update({f"pml_{rp}": pml.get(rp) for rp in return_periods})
        rows.append(row)
    return rows


def map_rows(portfolio: dict, analysis: dict, lat_step: float, lon_step: float) -> list[dict]:
    """Join each entered site with its matched centroid and cell, for drawing on a map.

    ``portfolio`` is the request (entered coordinates), ``analysis`` the response, both in the
    same site order. Sites without a centroid (out of zone) get no line and no cell.
    """
    rows = []
    for entered, site in zip(portfolio["sites"], analysis["sites"], strict=True):
        centroid, metrics = site["matched_centroid"], site["metrics"]
        rows.append(
            {
                "site_id": site["site_id"],
                "status": site["status"],
                "issues": ", ".join(site["issues"]) or "none",
                "asset_type": entered["asset_type"],
                "description": entered.get("description") or "",
                "lat": entered["lat"],
                "lon": entered["lon"],
                "centroid_lat": centroid["lat"] if centroid else None,
                "centroid_lon": centroid["lon"] if centroid else None,
                "distance_km": centroid["distance_km"] if centroid else None,
                "cell": cell_polygon(centroid["lat"], centroid["lon"], lat_step, lon_step)
                if centroid
                else None,
                "aal": metrics["aal"] if metrics else None,
                "color": STATUS_COLORS[site["status"]],
            }
        )
    return rows


def diversification_rows(analysis: dict) -> list[dict]:
    """Portfolio PML next to the sum of site PMLs, at each return period.

    The gap is the diversification: sites flooded in different years do not lose their worst
    year together, so the portfolio loss is lower than the sum.
    """
    evaluated = [_pml_by_return_period(s["metrics"]) for s in analysis["sites"] if s["metrics"]]
    return [
        {
            "return_period_years": p["return_period_years"],
            "portfolio": p["loss"],
            "sum_of_sites": sum(site[p["return_period_years"]] for site in evaluated),
        }
        for p in analysis["portfolio"]["pml"]
    ]


def curl_command(method: str, url: str, body: dict | None = None) -> str:
    """Equivalent ``curl`` command of a request, to copy into a terminal."""
    command = f"curl -s -X {method} '{url}'"
    if body is not None:
        # Inside single quotes, the shell needs each quote written as '\'' (close, escape, reopen).
        payload = json.dumps(body).replace("'", "'\\''")
        command += f" -H 'content-type: application/json' -d '{payload}'"
    return command

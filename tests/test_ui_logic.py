"""Tests for the pure functions of the web interface (no Streamlit, no network)."""

import json

import pytest

from ui.logic import (
    STATUS_COLORS,
    cell_polygon,
    curl_command,
    damage_ratio,
    diversification_rows,
    extent_polygon,
    map_rows,
    parse_portfolio_file,
    portfolio_summary,
    probability_at_least_one,
    result_rows,
    status_css,
)

STEP = 1 / 24  # river flood grid, 150 arc seconds

ANALYSIS = {
    "value_unit": "EUR",
    "counts": {"valid": 1, "warning": 0, "excluded": 1},
    "portfolio": {
        "aal": 100.0,
        "pml": [
            {"return_period_years": 100, "loss": 1000.0},
            {"return_period_years": 250, "loss": 3000.0},
        ],
    },
    "sites": [
        {
            "site_id": "plant",
            "status": "valid",
            "issues": [],
            "matched_centroid": {"lat": 44.5, "lon": -0.5, "distance_km": 1.2},
            "metrics": {
                "aal": 100.0,
                "pml": [
                    {"return_period_years": 100, "loss": 1000.0},
                    {"return_period_years": 250, "loss": 3000.0},
                ],
            },
        },
        {
            "site_id": "marseille",
            "status": "excluded",
            "issues": ["out_of_zone"],
            "matched_centroid": None,
            "metrics": None,
        },
    ],
}
PORTFOLIO = {
    "sites": [
        {
            "site_id": "plant",
            "lat": 44.51,
            "lon": -0.49,
            "value": 1e6,
            "asset_type": "industrial",
            "description": "riverside plant",
        },
        {"site_id": "marseille", "lat": 43.3, "lon": 5.4, "value": 1e6, "asset_type": "office"},
    ]
}


def test_cell_polygon_has_the_centroid_at_its_centre():
    corners = cell_polygon(44.5, -0.5, STEP, STEP)
    assert len(corners) == 4
    lons = [lon for lon, _ in corners]
    lats = [lat for _, lat in corners]
    assert (min(lons), max(lons)) == pytest.approx((-0.5 - STEP / 2, -0.5 + STEP / 2))
    assert (min(lats), max(lats)) == pytest.approx((44.5 - STEP / 2, 44.5 + STEP / 2))


def test_extent_polygon_follows_the_zone_corners():
    extent = {"lon_min": -1.3, "lat_min": 44.2, "lon_max": 0.35, "lat_max": 45.6}
    assert extent_polygon(extent) == [[-1.3, 44.2], [0.35, 44.2], [0.35, 45.6], [-1.3, 45.6]]


@pytest.mark.parametrize(
    ("return_period", "years", "expected"),
    [(100, 1, 0.01), (100, 30, 0.26), (100, 100, 0.634), (10, 10, 0.651)],
)
def test_probability_of_at_least_one_event(return_period, years, expected):
    # A "100-year flood" is a 1 % chance every year: 26 % over a 30-year mortgage.
    assert probability_at_least_one(return_period, years) == pytest.approx(expected, abs=1e-3)


def test_damage_ratio_interpolates_between_curve_points():
    curve = {"depths_m": [0.0, 1.0, 3.0], "damage_ratios": [0.0, 0.27, 0.70]}
    assert damage_ratio(curve, 1.0) == pytest.approx(0.27)
    assert damage_ratio(curve, 2.0) == pytest.approx((0.27 + 0.70) / 2)
    assert damage_ratio(curve, 10.0) == pytest.approx(0.70)  # flat beyond the last point


def test_result_rows_give_one_row_per_site_with_metrics_or_blanks():
    rows = result_rows(ANALYSIS)
    assert [r["site_id"] for r in rows] == ["plant", "marseille"]
    assert rows[0]["aal"] == 100.0
    assert rows[0]["pml_250"] == 3000.0
    assert rows[0]["distance_km"] == 1.2
    assert rows[1]["issues"] == "out_of_zone"
    assert rows[1]["aal"] is None
    assert rows[1]["distance_km"] is None


def test_map_rows_join_entered_point_and_matched_centroid():
    rows = map_rows(PORTFOLIO, ANALYSIS, STEP, STEP)
    plant, marseille = rows
    assert (plant["lat"], plant["lon"]) == (44.51, -0.49)
    assert (plant["centroid_lat"], plant["centroid_lon"]) == (44.5, -0.5)
    assert len(plant["cell"]) == 4
    assert plant["color"] != marseille["color"]
    # The optional description of a site is kept for the tooltip, empty when missing.
    assert plant["description"] == "riverside plant"
    assert marseille["description"] == ""
    # No centroid out of zone: no line and no cell to draw.
    assert marseille["centroid_lat"] is None
    assert marseille["cell"] is None


def test_diversification_compares_portfolio_with_sum_of_sites():
    second = {**ANALYSIS["sites"][0], "site_id": "warehouse"}
    analysis = {**ANALYSIS, "sites": [ANALYSIS["sites"][0], second]}
    rows = diversification_rows(analysis)
    assert rows == [
        {"return_period_years": 100, "portfolio": 1000.0, "sum_of_sites": 2000.0},
        {"return_period_years": 250, "portfolio": 3000.0, "sum_of_sites": 6000.0},
    ]


def test_curl_command_can_be_pasted_in_a_terminal():
    command = curl_command("POST", "http://127.0.0.1:8000/v1/analyze", {"sites": []})
    assert command == (
        "curl -s -X POST 'http://127.0.0.1:8000/v1/analyze' "
        "-H 'content-type: application/json' -d '{\"sites\": []}'"
    )
    assert curl_command("GET", "http://127.0.0.1:8000/health") == (
        "curl -s -X GET 'http://127.0.0.1:8000/health'"
    )


def test_curl_command_escapes_single_quotes_for_the_shell():
    command = curl_command("POST", "http://x/v1/validate", {"site_id": "l'usine"})
    assert command.endswith("""-d '{"site_id": "l'\\''usine"}'""")


def test_portfolio_summary_totals_values_by_asset_type():
    sites = [
        {"value": 2e6, "asset_type": "office"},
        {"value": 1e6, "asset_type": "industrial"},
        {"value": 3e6, "asset_type": "office"},
    ]
    summary = portfolio_summary(sites)
    assert summary["n_sites"] == 3
    assert summary["total_value"] == 6e6
    assert summary["value_by_asset_type"] == {"office": 5e6, "industrial": 1e6}


def test_portfolio_summary_skips_values_still_being_typed():
    # Rows being edited can have an empty value or type: count them, but not their value.
    sites = [{"value": 1e6, "asset_type": "office"}, {"value": None, "asset_type": None}]
    summary = portfolio_summary(sites)
    assert summary["n_sites"] == 2
    assert summary["total_value"] == 1e6
    assert summary["value_by_asset_type"] == {"office": 1e6}


def test_table_colours_match_map_colours():
    # Same RGB as the map dots, lighter so the text stays readable.
    for status, (red, green, blue, _) in STATUS_COLORS.items():
        assert status_css(status) == f"background-color: rgba({red}, {green}, {blue}, 0.25)"


CSV_HEADER = "site_id,lat,lon,value,asset_type,description\n"


def test_parse_csv_portfolio():
    content = CSV_HEADER + "plant,44.81,-0.55,5000000,industrial,Garonne bank\n"
    (site,) = parse_portfolio_file("sites.csv", content.encode())
    assert site == {
        "site_id": "plant",
        "lat": 44.81,
        "lon": -0.55,
        "value": 5e6,
        "asset_type": "industrial",
        "description": "Garonne bank",
    }


def test_parse_csv_from_french_excel():
    # French Excel exports use ";" between columns and "," as decimal mark.
    content = "site_id;lat;lon;value;asset_type\nplant;44,81;-0,55;5000000;industrial\n"
    (site,) = parse_portfolio_file("sites.csv", content.encode("utf-8-sig"))
    assert (site["lat"], site["lon"], site["value"]) == (44.81, -0.55, 5e6)
    assert site["description"] is None  # optional column


def test_parse_json_portfolio_as_api_request_or_plain_list():
    site = {"site_id": "a", "lat": 44.8, "lon": -0.5, "value": 1, "asset_type": "office"}
    for content in ({"sites": [site]}, [site]):
        (parsed,) = parse_portfolio_file("p.json", json.dumps(content).encode())
        assert parsed["site_id"] == "a"
        assert parsed["description"] is None


def test_parse_reports_missing_columns():
    content = "site_id,lat,value\nplant,44.8,1000\n"
    with pytest.raises(ValueError, match="asset_type, lon"):
        parse_portfolio_file("sites.csv", content.encode())


@pytest.mark.parametrize(
    ("name", "content"),
    [("sites.xlsx", b"PK..."), ("p.json", b"{not json"), ("p.json", b'{"other": 1}')],
)
def test_parse_rejects_unreadable_files(name, content):
    with pytest.raises(ValueError):
        parse_portfolio_file(name, content)

"""Educational web interface of the climrisk API, on insurance metrics and on the API itself.

It is an HTTP client of the API, like any other client: it never imports ``climrisk``.
Run the API first, then ``streamlit run ui/app.py``. See docs/decisions/008-web-interface.md.
"""

import json
import os
import time

import numpy as np
import pandas as pd
import pydeck as pdk
import requests
import streamlit as st
from logic import (
    OPTIONAL_COLUMNS,
    REQUIRED_COLUMNS,
    STATUS_COLORS,
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

API_URL = os.environ.get("CLIMRISK_API_URL", "http://127.0.0.1:8000").rstrip("/")
CODE_URL = "https://github.com/Victoire-gorge/physical-climrisk-api/blob/main"
# 10,000 sites take about 0.6 s; a hosted API waking up from sleep can take about a minute.
REQUEST_TIMEOUT_S = 90
MAX_LOGGED_EXCHANGES = 10

ISSUE_EXPLANATIONS = {
    "invalid_value": "The value must be a finite number above 0.",
    "unknown_asset_type": "The asset type has no vulnerability curve.",
    "duplicate_site_id": "Two sites share this id, so results could not be told apart.",
    "out_of_zone": "The site lies outside the area covered by the loaded hazard.",
    "out_of_grid": "No hazard cell is close enough (more than 3 cell half-diagonals away).",
    "neighbour_cell": "The site's own cell has no data (sea, estuary): the nearest cell is used.",
}

st.set_page_config(page_title="climrisk", page_icon="🌊", layout="wide")


# --- API calls -------------------------------------------------------------------------------


def call_api(method: str, path: str, body: dict | None = None) -> dict:
    """Send one request, log it for the "Under the hood" tab, and return the exchange."""
    url = f"{API_URL}{path}"
    start = time.perf_counter()
    response = requests.request(method, url, json=body, timeout=REQUEST_TIMEOUT_S)
    exchange = {
        "method": method,
        "path": path,
        "url": url,
        "body": body,
        "status": response.status_code,
        "elapsed_ms": round((time.perf_counter() - start) * 1000),
        "response": response.json(),
    }
    log = st.session_state.setdefault("exchanges", [])
    log.insert(0, exchange)
    del log[MAX_LOGGED_EXCHANGES:]
    return exchange


def load_reference_data() -> None:
    """Fetch, once per session, what the interface needs to know about the API."""
    if "hazard" in st.session_state:
        return
    try:
        st.session_state.hazard = call_api("GET", "/v1/hazards")["response"][0]
    except requests.ConnectionError:
        st.error(
            f"The API is not reachable at {API_URL}. Start it in another terminal with "
            "`uvicorn --factory climrisk.api.app:create_app`, then reload this page."
        )
        st.stop()
    st.session_state.curves = call_api("GET", "/v1/vulnerability-curves")["response"]
    # The demo portfolio is the example request published in the API's OpenAPI description.
    spec = call_api("GET", "/openapi.json")["response"]
    request_body = spec["paths"]["/v1/analyze"]["post"]["requestBody"]
    demo = request_body["content"]["application/json"]["examples"]["demo"]["value"]
    st.session_state.demo_df = pd.DataFrame(demo["sites"])


def analyze(portfolio_df: pd.DataFrame) -> None:
    """Send the edited portfolio to /v1/analyze and keep the request and response."""
    # Empty cells become null, which the API rejects as a malformed request (422).
    clean = portfolio_df.astype(object).where(portfolio_df.notna(), None)
    body = {"sites": clean.to_dict("records")}
    exchange = call_api("POST", "/v1/analyze", body)
    st.session_state.last_status = exchange["status"]
    if exchange["status"] == 200:
        st.session_state.analysis = exchange["response"]
        st.session_state.analysed_portfolio = body
    else:
        st.session_state.analysis = None
        st.session_state.error = exchange["response"]


def money(value: float | None) -> str:
    return "" if value is None else f"{value:,.0f} €"


# --- sidebar ---------------------------------------------------------------------------------

load_reference_data()
hazard = st.session_state.hazard

with st.sidebar:
    st.title("climrisk")
    st.caption(
        "Learning project. Results are illustrative and must not be used for real decisions."
    )
    st.markdown(
        f"""
**API**: `{API_URL}`
[interactive docs]({API_URL}/docs) · [OpenAPI spec]({API_URL}/openapi.json)

**Hazard loaded**: {hazard["hazard_type"].replace("_", " ")}, {hazard["scenario"]}
({hazard["year_range"].replace("_", " to ")}), {hazard["simulated_years"]:.0f} simulated years,
depth in {hazard["intensity_unit"]}.

**Grid cell**: {hazard["grid"]["lat_step_deg"]:.4f}° x {hazard["grid"]["lon_step_deg"]:.4f}°,
about 4.6 x 3.3 km here.
"""
    )

tab_portfolio, tab_insurance, tab_api = st.tabs(
    ["1. Portfolio, map and results", "2. Insurance basics", "3. Under the hood"]
)

# Starting point of an import: the expected columns, no site yet.
EMPTY_PORTFOLIO = pd.DataFrame(
    {
        "site_id": pd.Series(dtype=str),
        "lat": pd.Series(dtype=float),
        "lon": pd.Series(dtype=float),
        "value": pd.Series(dtype=float),
        "asset_type": pd.Series(dtype=str),
        "description": pd.Series(dtype=str),
    }
)

COLUMN_HELP = {
    "site_id": "Your identifier for the site, unique in the portfolio.",
    "description": "Free text for you (label, address). The computation does not use it.",
    "asset_type": "Chooses the damage curve: how much of the value a given water depth destroys.",
    "value": "Insured value in EUR: the most that can be lost on this site.",
    "lat": "Latitude in degrees (north positive).",
    "lon": "Longitude in degrees (east positive, so Gironde is negative).",
}


def zone_layer() -> pdk.Layer:
    """Blue frame of the zone served by the deployment."""
    return pdk.Layer(
        "PolygonLayer",
        [{"polygon": extent_polygon(hazard["extent"])}],
        get_polygon="polygon",
        filled=False,
        stroked=True,
        get_line_color=[40, 90, 200],
        line_width_min_pixels=2,
    )


def show_map(layers: list[pdk.Layer], tooltip_html: str) -> None:
    extent = hazard["extent"]
    view = pdk.ViewState(
        latitude=(extent["lat_min"] + extent["lat_max"]) / 2,
        longitude=(extent["lon_min"] + extent["lon_max"]) / 2,
        zoom=8,
    )
    deck = pdk.Deck(
        layers=layers, initial_view_state=view, tooltip={"html": tooltip_html}, map_style="light"
    )
    st.pydeck_chart(deck)


# --- 1. portfolio, map and results -----------------------------------------------------------

with tab_portfolio:
    st.header("Portfolio")
    st.markdown(
        "A **portfolio** is the list of **sites** an insurer or an owner wants to assess: for "
        "each one, where it is, what kind of asset it is, and how much it is worth."
    )
    source = st.radio(
        "Portfolio to assess",
        ["Demo portfolio", "Import your own file"],
        horizontal=True,
        help="Start from the demo, or upload a CSV or JSON file of your own sites.",
    )
    if source == "Demo portfolio":
        portfolio_df, editor_key = st.session_state.demo_df, "editor_demo"
        with st.expander("About the demo portfolio", expanded=True):
            st.markdown(
                "Ten **fictitious** sites in Gironde (made-up names and values), chosen so "
                "that each one shows a different case. Read the *description* column for the "
                "role of each site.\n"
                "- **Dry sites** (Bordeaux, Merignac): their cell is never flooded in the data.\n"
                "- **Riverside sites** (Begles, Libourne, Langon): flooded in some simulated "
                "years.\n"
                "- **A wine estate declared as two sites** at the same point: the buildings "
                "(cellars, stock) with the industrial curve, the vines with the crop curve. One "
                "curve for the whole estate would be wrong for one of the two, and the owner "
                "knows the split.\n"
                "- **Edge cases**: Blaye on the estuary bank (a neighbour cell is used), an "
                "offshore platform (too far from any cell) and Marseille (outside the zone).\n\n"
                "Edit anything in the table: add rows, change a value, a type or a location."
            )
    else:
        with st.expander("File format", expanded=True):
            st.markdown(
                "**CSV**: one row per site, with the columns `site_id, lat, lon, value, "
                "asset_type` and optionally `description`. A file saved by a French Excel "
                "(`;` between columns, `,` as decimal mark) is fine too.\n\n"
                '**JSON**: the API request format `{"sites": [...]}`, or a plain list of sites.'
                "\n\nValues are checked by the API, site by site, when you analyse the portfolio."
            )
            st.download_button(
                "Download a CSV template (the demo portfolio)",
                data=st.session_state.demo_df[list(REQUIRED_COLUMNS + OPTIONAL_COLUMNS)].to_csv(
                    index=False
                ),
                file_name="portfolio_template.csv",
                mime="text/csv",
            )
        uploaded = st.file_uploader("Your portfolio file", type=["csv", "json"])
        portfolio_df = EMPTY_PORTFOLIO
        if uploaded is None:
            st.caption("No file yet: you can also type sites directly in the empty table below.")
        else:
            try:
                portfolio_df = pd.DataFrame(
                    parse_portfolio_file(uploaded.name, uploaded.getvalue())
                )
                st.success(f"{len(portfolio_df)} sites read from {uploaded.name}.")
            except ValueError as error:
                st.error(f"{uploaded.name} could not be read. {error}")
        editor_key = f"editor_file_{uploaded.file_id if uploaded else 'none'}"

    # A new source or a new file starts afresh: results of the previous portfolio are cleared.
    if st.session_state.get("editor_key") != editor_key:
        st.session_state.editor_key = editor_key
        st.session_state.analysis = None
        st.session_state.last_status = None

    edited = st.data_editor(
        portfolio_df,
        num_rows="dynamic",
        width="stretch",
        column_order=["site_id", "description", "asset_type", "value", "lat", "lon"],
        column_config={
            "site_id": st.column_config.TextColumn("site_id", help=COLUMN_HELP["site_id"]),
            "description": st.column_config.TextColumn(
                "description", help=COLUMN_HELP["description"], width="large"
            ),
            "asset_type": st.column_config.SelectboxColumn(
                "asset_type",
                options=hazard["asset_types"] + ["castle"],
                required=True,
                help=COLUMN_HELP["asset_type"],
            ),
            "value": st.column_config.NumberColumn(
                "value (EUR)", format="%.0f", help=COLUMN_HELP["value"]
            ),
            "lat": st.column_config.NumberColumn("lat", format="%.4f", help=COLUMN_HELP["lat"]),
            "lon": st.column_config.NumberColumn("lon", format="%.4f", help=COLUMN_HELP["lon"]),
        },
        key=editor_key,
    )
    st.caption(
        "Every row of the table is analysed. The tick boxes on the left only select rows to "
        "delete: tick them, then press the bin icon above the table (or the Delete key). "
        "Hover a column header for its meaning. `castle` is in the type list on purpose: it has "
        "no damage curve, so you can see the API exclude one site without rejecting the others."
    )

    # Summary of the table as edited, before any computation.
    records = edited.assign(value=pd.to_numeric(edited["value"], errors="coerce")).to_dict(
        "records"
    )
    summary = portfolio_summary(records)
    cols = st.columns([1, 1, 1, 2])
    cols[0].metric("Sites", summary["n_sites"])
    cols[1].metric("Total insured value", money(summary["total_value"]))
    cols[2].metric(
        "Average per site",
        money(summary["total_value"] / summary["n_sites"]) if summary["n_sites"] else "",
    )
    if summary["value_by_asset_type"]:
        by_type = pd.DataFrame({"value (EUR)": summary["value_by_asset_type"]}).rename_axis(
            "asset type"
        )
        cols[3].bar_chart(by_type, horizontal=True, height=180)

    if st.button("Analyze portfolio", type="primary"):
        analyze(edited)

    analysis = st.session_state.get("analysis")
    if st.session_state.get("last_status") not in (None, 200):
        st.error(
            f"The API answered {st.session_state.last_status}. "
            "See the details in the 'Under the hood' tab."
        )
        st.json(st.session_state.error, expanded=False)

    if not analysis:
        st.subheader("Where the sites are")
        located = [
            {**r, "value_label": money(r["value"]) if np.isfinite(r["value"]) else ""}
            for r in records
            if isinstance(r.get("lat"), float | int) and isinstance(r.get("lon"), float | int)
        ]
        points = pdk.Layer(
            "ScatterplotLayer",
            located,
            get_position=["lon", "lat"],
            get_fill_color=[70, 70, 70, 220],
            get_radius=400,
            radius_min_pixels=6,
            pickable=True,
        )
        show_map(
            [zone_layer(), points],
            "<b>{site_id}</b> ({asset_type}, {value_label})<br/>{description}",
        )
        st.caption("Click 'Analyze portfolio' to see the hazard cell used for each site.")
    else:
        st.subheader("Map: the site as entered, and the hazard cell the model uses")
        counts, portfolio = analysis["counts"], analysis["portfolio"]
        pml = {p["return_period_years"]: p["loss"] for p in portfolio["pml"]}
        cols = st.columns(5)
        cols[0].metric("Valid sites", counts["valid"])
        cols[1].metric("Warnings", counts["warning"])
        cols[2].metric("Excluded", counts["excluded"])
        cols[3].metric("Portfolio AAL", money(portfolio["aal"]))
        cols[4].metric("Portfolio 100-year loss", money(pml.get(100)))

        rows = map_rows(
            st.session_state.analysed_portfolio,
            analysis,
            hazard["grid"]["lat_step_deg"],
            hazard["grid"]["lon_step_deg"],
        )
        for row in rows:  # text shown when hovering a site
            row["distance_label"] = (
                "none" if row["distance_km"] is None else f"{row['distance_km']:.2f} km"
            )
            row["aal_label"] = "not computed" if row["aal"] is None else money(row["aal"])
        matched = [r for r in rows if r["cell"] is not None]
        for row in matched:
            row["cell_fill"] = row["color"][:3] + [45]

        layers = [
            zone_layer(),
            pdk.Layer(
                "PolygonLayer",
                matched,
                get_polygon="cell",
                get_fill_color="cell_fill",
                get_line_color="color",
                line_width_min_pixels=1,
            ),
            pdk.Layer(
                "LineLayer",
                matched,
                get_source_position=["lon", "lat"],
                get_target_position=["centroid_lon", "centroid_lat"],
                get_color=[30, 30, 30],
                get_width=2,
            ),
            pdk.Layer(
                "ScatterplotLayer",
                matched,
                get_position=["centroid_lon", "centroid_lat"],
                get_fill_color=[90, 90, 90],
                get_radius=150,
                radius_min_pixels=3,
            ),
            pdk.Layer(
                "ScatterplotLayer",
                rows,
                get_position=["lon", "lat"],
                get_fill_color="color",
                get_radius=400,
                radius_min_pixels=6,
                pickable=True,
            ),
        ]
        show_map(
            layers,
            "<b>{site_id}</b> ({asset_type})<br/>{description}<br/>status: {status}"
            "<br/>issues: {issues}<br/>distance to centroid: {distance_label}<br/>AAL: {aal_label}",
        )
        legend = " · ".join(
            f"<span style='color:rgb({c[0]},{c[1]},{c[2]})'>●</span> {status}"
            for status, c in STATUS_COLORS.items()
        )
        st.markdown(legend, unsafe_allow_html=True)
        st.info(
            "**How to read the map.** Each coloured dot is a site as entered. The model does not "
            "see that exact point: it uses the flood depths of one grid cell (the square), whose "
            "centre is the grey dot, joined to the site by a line. The blue frame is the zone the "
            "deployment serves.\n\n"
            "- **Blaye** sits on the estuary bank: its own cell has no data (water), so the "
            "neighbour land cell is used and the site gets a warning.\n"
            "- **Saint-Emilion** is on a hillside, but its 4.6 km cell also covers the Dordogne "
            "plain: the model cannot see the slope and gives losses a real assessment would not.\n"
            "- **Marseille** is outside the zone: it is listed in the results, not drawn here."
        )

        st.subheader("Results per site")
        table = pd.DataFrame(result_rows(analysis))
        table.insert(
            1,
            "description",
            [s.get("description") or "" for s in st.session_state.analysed_portfolio["sites"]],
        )
        money_columns = [c for c in table.columns if c == "aal" or c.startswith("pml_")]
        styled = (
            table.style.apply(lambda row: [status_css(row["status"])] * len(row), axis=1)
            .format("{:,.0f}", subset=money_columns, na_rep="")
            .format("{:.2f}", subset=["distance_km"], na_rep="")
        )
        st.dataframe(styled, width="stretch", hide_index=True)
        st.markdown(
            "Rows have the colour of the site on the map. **AAL**: average annual loss. "
            "**pml_T**: probable maximum loss at a return period of T years, the loss exceeded on "
            "average once every T years. All in EUR. The portfolio totals only count sites that "
            "were evaluated."
        )
        seen = sorted({issue for site in analysis["sites"] for issue in site["issues"]})
        if seen:
            st.markdown("**Why a site has a warning or is excluded**")
            for issue in seen:
                st.markdown(f"- `{issue}`: {ISSUE_EXPLANATIONS.get(issue, '')}")
        st.download_button(
            "Download the raw JSON response",
            data=json.dumps(analysis, indent=2),
            file_name="analysis.json",
            mime="application/json",
        )

# --- 2. insurance basics ---------------------------------------------------------------------

with tab_insurance:
    st.header("Insurance basics")

    st.subheader("The three building blocks of a catastrophe model")
    cols = st.columns(3)
    cols[0].markdown(
        "**Hazard**: how strong the event is, where, and how often. Here: river flood depth, "
        f"simulated over {hazard['simulated_years']:.0f} years on a grid of cells."
    )
    cols[1].markdown(
        "**Exposure**: what is at risk, where, and for how much. Here: your sites, their "
        "location, value and asset type."
    )
    cols[2].markdown(
        "**Vulnerability**: how much damage a given intensity causes. Here: the share of the "
        "value lost as a function of water depth, one curve per asset type."
    )
    st.markdown(
        "For every simulated year, the model combines the three: "
        "**loss = value x damage ratio(depth) x flooded share of the cell**."
    )

    st.subheader("Vulnerability curves")
    curves = st.session_state.curves
    depths = np.round(np.arange(0, 6.01, 0.05), 2)
    chart = pd.DataFrame(
        {c["asset_type"]: [damage_ratio(c, d) for d in depths] for c in curves}, index=depths
    )
    chart.index.name = "water depth (m)"
    st.line_chart(chart, x_label="water depth (m)", y_label="damage ratio")
    depth = st.slider("Water depth (m)", 0.0, 6.0, 1.0, 0.1)
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "asset_type": c["asset_type"],
                    "JRC sector": c["jrc_sector"],
                    "damage ratio": f"{damage_ratio(c, depth):.0%}",
                    "loss on a 1 M€ asset": money(1e6 * damage_ratio(c, depth)),
                }
                for c in curves
            ]
        ),
        hide_index=True,
    )
    st.caption(
        "Curves from the JRC European depth-damage database (Huizinga et al., 2017). Logistics "
        "uses the industrial curve: JRC has no warehouse curve. Cropland covers crops only."
    )

    st.subheader("AAL and PML: the average year and the bad year")
    st.markdown(
        "- **AAL (average annual loss)** is the mean of the simulated yearly losses. It is what a "
        "*pure premium* must cover on average, before costs and margin.\n"
        "- **PML (probable maximum loss) at T years** is the loss exceeded on average once every "
        "T years. It tells how much capital must absorb a bad year.\n"
        f"- With {hazard['simulated_years']:.0f} simulated years ranked from worst to best, the "
        "100-year loss is the 10th worst: only 9 years do worse, at most 1 year in 100."
    )
    analysis = st.session_state.get("analysis")
    evaluated = [s for s in analysis["sites"] if s["metrics"]] if analysis else []
    if evaluated:
        names = [s["site_id"] for s in evaluated]
        most_exposed = max(evaluated, key=lambda s: s["metrics"]["aal"])["site_id"]
        chosen = st.selectbox("Site", names, index=names.index(most_exposed))
        metrics = next(s for s in evaluated if s["site_id"] == chosen)["metrics"]
        pml_table = pd.DataFrame(metrics["pml"]).set_index("return_period_years")
        cols = st.columns([1, 2])
        cols[0].metric("AAL", money(metrics["aal"]))
        cols[0].markdown(
            "A zero at short return periods is normal: a site flooded once every 50 years has no "
            "loss in a typical 10-year window."
        )
        cols[1].bar_chart(pml_table, x_label="return period (years)", y_label="loss (EUR)")
    else:
        st.info("Analyse a portfolio in the first tab to see the PML of a site here.")

    st.subheader('A "100-year flood" is not "once a century"')
    st.markdown(
        "A T-year event has a **1/T chance every year**, independently of the past. Over n years "
        "the chance of at least one is 1 - (1 - 1/T)^n."
    )
    cols = st.columns(3)
    period = cols[0].slider("Return period (years)", 10, 500, 100, 10)
    horizon = cols[1].slider("Horizon (years)", 1, 100, 30)
    cols[2].metric(
        f"Chance of at least one {period}-year flood in {horizon} years",
        f"{probability_at_least_one(period, horizon):.0%}",
    )
    st.caption(
        "A 30-year mortgage on a site in a 100-year flood zone: 26 % chance of at least one."
    )

    st.subheader("Diversification: why the portfolio loss is not the sum")
    if analysis:
        diversification = pd.DataFrame(diversification_rows(analysis)).set_index(
            "return_period_years"
        )
        st.bar_chart(
            diversification, stack=False, x_label="return period (years)", y_label="loss (EUR)"
        )
        st.markdown(
            "The portfolio PML is read on the **total loss of each simulated year**. Sites are "
            "rarely flooded in the same years, so their worst years do not add up: summing site "
            "PMLs would overstate the risk. AAL, an average, does add up."
        )
    else:
        st.info("Analyse a portfolio in the first tab to compare both here.")

    st.subheader("What this model does not tell")
    st.markdown(
        "- **Direct damage only**: business interruption (lost activity) is not modelled.\n"
        "- **Resolution**: one cell is about 4.6 x 3.3 km; slopes, dikes and floors are "
        "invisible.\n"
        f"- **{hazard['simulated_years']:.0f} years are not independent**: they are 46 models "
        "simulating the same 20 years, so the real uncertainty is larger.\n"
        "- **Historical climate**: no climate change scenario yet.\n"
        "- **Generic curves**: European averages, not your building."
    )

# --- 3. under the hood -----------------------------------------------------------------------

with tab_api:
    st.header("Under the hood: the API")
    st.markdown(
        "This interface is just a client: everything it shows comes from HTTP requests to the "
        "API, listed below. Any other program (a script, a spreadsheet, another service) could "
        "send the same requests."
    )
    cols = st.columns(2)
    cols[0].markdown(
        """
| Endpoint | Role |
|---|---|
| `GET /health` | Is the service up? (for a load balancer) |
| `GET /v1/hazards` | What hazard, zone and grid are loaded |
| `GET /v1/vulnerability-curves` | Damage curves used |
| `POST /v1/validate` | Check each site, no computation |
| `POST /v1/analyze` | Validate, then compute AAL and PML |
"""
    )
    cols[1].markdown(
        """
| Status | Meaning here |
|---|---|
| `200` | Success. Invalid sites are excluded with their reasons |
| `422` | Malformed request (missing field, wrong type, 0 or too many sites), or all excluded |
"""
    )

    st.subheader("What happens on the server for /v1/analyze")
    code = {
        "schemas": f"{CODE_URL}/src/climrisk/api/schemas.py",
        "validation": f"{CODE_URL}/src/climrisk/science/validation.py",
        "exposure": f"{CODE_URL}/src/climrisk/science/exposure.py",
        "impact": f"{CODE_URL}/src/climrisk/science/impact.py",
        "decision_005": f"{CODE_URL}/docs/decisions/005-loss-metrics.md",
        "decision_006": f"{CODE_URL}/docs/decisions/006-site-validation.md",
    }
    st.markdown(
        f"""
1. **Shape check** by Pydantic: fields and types ([schemas.py]({code["schemas"]})).
2. **Business rules**, site by site: value, asset type, zone, distance to the grid
   ([validation.py]({code["validation"]}), [decision 006]({code["decision_006"]})).
3. **Matching** each site to its nearest grid cell with CLIMADA
   ([exposure.py]({code["exposure"]})).
4. **Impact**: CLIMADA's `ImpactCalc` computes the loss of every site in every simulated year
   ([impact.py]({code["impact"]}), [decision 005]({code["decision_005"]})).
5. **Metrics**: AAL and PML per site and for the portfolio, rounded in the response.

The hazard file is loaded once when the service starts, never during a request.
"""
    )

    st.subheader("Try the error cases")
    st.markdown("Each button sends a request; the exchange appears at the top of the list below.")
    cols = st.columns(3)
    site = {"site_id": "a", "lat": 44.84, "lon": -0.58, "value": 1e6, "asset_type": "office"}
    if cols[0].button("Malformed request (missing lon)"):
        call_api("POST", "/v1/validate", {"sites": [{k: v for k, v in site.items() if k != "lon"}]})
    if cols[1].button("Unknown asset type"):
        call_api(
            "POST",
            "/v1/validate",
            {"sites": [{**site, "asset_type": "castle"}, site | {"site_id": "b"}]},
        )
    if cols[2].button("Every site excluded"):
        call_api("POST", "/v1/analyze", {"sites": [{**site, "lat": 43.3, "lon": 5.4}]})
    st.caption(
        "A malformed request is rejected as a whole (422). An unknown asset type only excludes "
        "that site (200). When no site is left to compute, /v1/analyze answers 422 with the "
        "reasons."
    )

    st.subheader("Requests sent by this page")
    for exchange in st.session_state.get("exchanges", []):
        title = (
            f"{exchange['method']} {exchange['path']} → {exchange['status']} "
            f"in {exchange['elapsed_ms']} ms"
        )
        with st.expander(title):
            st.code(curl_command(exchange["method"], exchange["url"], exchange["body"]), "bash")
            cols = st.columns(2)
            cols[0].markdown("**Request body**")
            cols[0].json(exchange["body"] if exchange["body"] is not None else {}, expanded=False)
            cols[1].markdown("**Response**")
            cols[1].json(exchange["response"], expanded=False)

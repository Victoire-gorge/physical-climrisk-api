# physical-climrisk-api

A learning project that turns [CLIMADA](https://github.com/CLIMADA-project/climada_python)
(ETH Zurich) into a small web service: it receives a portfolio of sites and returns physical
climate risk indicators per site and per portfolio.

Work in progress. Results are illustrative and must not be used for real decisions.

## Run locally

```bash
micromamba create -n climrisk -f conda-lock.yml
micromamba activate climrisk
pip install -e . --no-deps
python -m climrisk.prepare                       # download and crop the zone hazard (once)
uvicorn --factory climrisk.api.app:create_app    # interactive docs at http://127.0.0.1:8000/docs
```

Endpoints: `GET /health`, `GET /v1/hazards`, `POST /v1/validate`, `POST /v1/analyze`.
See `docs/decisions/` for the reasoning behind each choice.

## Demo portfolio

[`src/climrisk/api/demo_portfolio.json`](src/climrisk/api/demo_portfolio.json) holds ten
fictitious sites in Gironde (made-up names and values). It prefills the examples of `/docs`, and
can be sent from the command line:

```bash
curl -s -X POST http://127.0.0.1:8000/v1/analyze \
  -H 'content-type: application/json' -d @src/climrisk/api/demo_portfolio.json
```

Each site shows one case. Results below were measured on the historical river flood set (920
simulated years); losses are in EUR.

| Site | Asset type | Shows | Status | AAL | 100-year loss |
|---|---|---|---|---|---|
| `bordeaux_centre_office` | office | dry site | valid | 0 | 0 |
| `merignac_logistics_hub` | logistics | dry site, industrial curve | valid | 0 | 0 |
| `begles_riverside_plant` | industrial | Garonne bank | valid | 4,707 | 187,893 |
| `libourne_warehouse` | logistics | Isle and Dordogne confluence | valid | 27,077 | 1,076,678 |
| `langon_plant` | industrial | upstream Garonne | valid | 1,222 | 83,566 |
| `saint_emilion_estate_buildings` | industrial | wine estate, buildings | valid | 7,770 | 0 |
| `saint_emilion_estate_vines` | cropland | same estate, vines, same point | valid | 5,180 | 0 |
| `blaye_office` | office | estuary bank, neighbour cell used | warning | 0 | 0 |
| `offshore_platform` | industrial | at sea, 12.9 km from any cell | excluded (`out_of_grid`) | | |
| `marseille_office` | office | outside the zone | excluded (`out_of_zone`) | | |

Portfolio: AAL 45,956, 100-year loss 1,102,312, 250-year loss 4,406,400. At 250 years the site
losses add up to 4.91 million: sites flooded in different years do not lose their worst year
together, so the portfolio loss is lower than the sum.

**Resolution limit, on purpose.** Saint-Emilion sits on a hillside, but its hazard cell (about
4.6 x 3.3 km) also covers the Dordogne plain. The model cannot see the slope: the estate has no
100-year loss, but a 250-year loss of 84 % of its building value. A real assessment would need a
finer flood map, or the elevation of the site compared with the flood depth.

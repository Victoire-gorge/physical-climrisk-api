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

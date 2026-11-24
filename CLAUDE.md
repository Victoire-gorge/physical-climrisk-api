# physical-climrisk-api

Learning project: a FastAPI service that wraps CLIMADA to compute physical
climate risk indicators for a portfolio of sites. Results are not suitable
for real decisions.

## Architecture
- `src/climrisk/science/`: CLIMADA logic (hazard, exposure, vulnerability, impact). No FastAPI or HTTP imports.
- `src/climrisk/api/`: FastAPI routes, Pydantic schemas, error handling.
- `ui/`: Streamlit interface, an HTTP client of the API. Never imports `climrisk`.
- `src/climrisk/config.py`: settings from environment variables (pydantic-settings).
- Validation rules live in one place and are reused by every endpoint.
- The geographic zone comes from configuration. Out-of-zone checks use the extent of the loaded hazard, never coordinates copied into code.

## Rules
- KISS: no abstraction until a second real implementation exists. No factories, strategies, base classes "for later", or empty modules.
- Reuse CLIMADA structures (Hazard, Exposures, ImpactFuncSet, ImpactCalc, Impact); do not reimplement them.
- Targeted diffs: do not reformat or refactor neighbouring code; report dead code instead of silently deleting it.
- One source of truth for each list or rule. Named constants for thresholds, with the measurement that justifies them in a comment.
- Use pathlib for paths. Type hints and docstrings on public functions.
- Pure functions separated from side effects (downloads, file reads) so tests run offline.
- No loading or downloading in a request path.
- Never commit secrets, `.env`, or large data files.

## Vocabulary (one term per concept)
| Term | Meaning |
|---|---|
| site | one location and its asset |
| portfolio | the set of sites submitted by a client |
| zone | the geographic area served by the deployment (from configuration) |
| hazard | CLIMADA hazard set (here: river flood depth) |
| exposure | CLIMADA Exposures built from a portfolio |
| vulnerability | impact function linking intensity to damage ratio |
| impact | CLIMADA impact computation result |
| return period | average recurrence interval of an intensity or loss, in years |
| AAL | average annual loss |
| PML | probable maximum loss at a given return period |

## Commands
- Environment: `micromamba create -n climrisk -f conda-lock.yml` then `pip install -e . --no-deps`
- Update lock after editing `environment.yml`: `conda-lock lock -f environment.yml -p osx-arm64 -p linux-64`
- Prepare the zone hazard file (once): `python -m climrisk.prepare`
- Serve the API: `uvicorn --factory climrisk.api.app:create_app` (docs at `/docs`)
- Web interface (separate env `climrisk-ui`, created from `ui/conda-lock.yml`): `streamlit run ui/app.py`
- Update the interface lock after editing `ui/environment.yml`: `conda-lock lock -f ui/environment.yml -p osx-arm64 -p linux-64 --lockfile ui/conda-lock.yml`
- Tests: `pytest`
- Lint: `ruff check . && ruff format --check .`

## Conventions
- Documentation, docstrings and commit messages in English. No em dashes.
- Conventional Commits: `type: description` in imperative, lowercase, no final period; body explains why.
- Write the test before implementing a pure transformation. Fixed random seeds.
- Architecture decisions go in `docs/decisions/NNN-title.md` (context, options, decision, consequences).

# 007. HTTP API contract: endpoints, response shapes, errors and limits

## Context
The science modules validate a portfolio (006) and compute its loss metrics (005). The service
exposes them over HTTP, without loading anything in a request path, and must stay deployable on
AWS (container on Fargate, or Lambda).

## Options
**Response of `/v1/analyze`**
1. **Every site, in input order**, each with its validation and `metrics` (null when excluded).
2. Two lists: results of evaluated sites, and excluded sites.

**PML in responses**
1. **A list** `[{return_period_years, loss}]`.
2. A mapping `{"100": loss}`: JSON keys are strings, less typed in OpenAPI.

**Route functions**
1. **Plain `def`**: FastAPI runs them in a thread pool.
2. `async def`: the CPU-bound CLIMADA computation would block the event loop, hence every
   other request, while it runs.

## Decision
Option 1 in each case.
- Endpoints: `GET /health` (liveness for a load balancer), `GET /v1/hazards` (zone extent, grid
  step, simulated years, return periods, asset types), `POST /v1/validate`, `POST /v1/analyze`.
- `/v1/hazards` returns a list holding one hazard: adding a hazard later adds an element without
  changing the response shape.
- Startup (`lifespan`) loads the prepared hazard file, checks its type, its grid (006) and its
  return periods (005), and keeps them in `app.state`. A missing file stops the service with a
  message pointing to `python -m climrisk.prepare`. Requests only read this state.
- `create_app(settings)` takes settings, so tests write a small hazard file to a temporary
  directory and exercise the real loading path offline. The server runs with
  `uvicorn --factory climrisk.api.app:create_app`, which reads nothing at import time.
- Errors: a malformed request (missing field, text instead of a number, 0 or more than
  `MAX_SITES` sites) gets FastAPI's standard 422. An invalid site is excluded with its issues
  (200). `/v1/analyze` with every site excluded gets 422 with the validation report in `detail`.
- `MAX_SITES = 10,000`. Measured on the Gironde hazard with 10,000 random sites: 0.56 s for
  `/v1/analyze`, a 3.5 MB response for a 1.2 MB request, 490 MB process peak. AWS Lambda caps a
  synchronous response at 6 MB.

## Consequences
- A client maps results back to its sites by position or by `site_id`, and sees on the same row
  why a site has no metrics.
- `/v1/validate` and `/v1/analyze` call the same validation function, and a test checks they
  report identical statuses, issues and matched centroids.
- Larger portfolios need batching by the client, or an asynchronous job (outside P0). AAL adds
  up over batches; the portfolio PML does not and needs the yearly losses of every batch.
- No authentication or rate limiting yet: an API gateway would provide them on AWS.

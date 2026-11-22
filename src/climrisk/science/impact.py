"""Impact: run CLIMADA's impact calculation and derive loss metrics (AAL, PML).

See docs/decisions/005-loss-metrics.md.
"""

from collections.abc import Sequence
from typing import NamedTuple

import pandas as pd
from climada.engine import Impact, ImpactCalc
from climada.entity import Exposures
from climada.hazard import Hazard

from climrisk.science.vulnerability import impact_function_set

# Return periods (years) reported for every site and for the portfolio. The Gironde river flood
# set holds 920 simulated years (46 models x 20 years, frequency 1/920 each): the 250-year loss
# still rests on about 3.7 simulated years beyond it, whereas a 500-year loss would rest on 1.8.
RETURN_PERIODS_YEARS = (10, 50, 100, 250)

# Empirical exceedance loss, read on CLIMADA's step function. Unlike the default "interpolate",
# it returns 0 (not NaN) when no loss is exceeded at a return period, e.g. a never flooded site.
PML_METHOD = "stepfunction"


class RiskMetrics(NamedTuple):
    """Loss metrics of a portfolio, in the exposure value unit.

    ``sites`` has one row per site, in portfolio order, with columns ``site_id``, ``aal`` and
    ``pml_<return period>``. ``portfolio_pml`` maps each return period to the portfolio loss.
    """

    sites: pd.DataFrame
    portfolio_aal: float
    portfolio_pml: dict[int, float]


def check_return_periods(hazard: Hazard, return_periods: Sequence[int]) -> None:
    """Check that every return period fits within the years simulated by ``hazard``.

    With equally likely events, the longest observable return period is 1 / frequency, i.e. the
    number of simulated years. Beyond it the step function would silently repeat the largest
    loss, so a longer return period is refused.

    Raises:
        ValueError: if a return period exceeds the longest observable one.
    """
    longest = 1 / hazard.frequency.min()
    too_long = [rp for rp in return_periods if rp > longest]
    if too_long:
        raise ValueError(
            f"Return periods {too_long} exceed the {longest:g} years simulated by the hazard."
        )


def compute_impact(exposures: Exposures, hazard: Hazard) -> Impact:
    """Compute the flood impact of ``exposures``, keeping the centroids they already carry.

    ``assign_centroids=False`` keeps the matching done by ``nearest_centroid``: by default
    CLIMADA would match again and overwrite it. ``save_mat=True`` keeps the loss of each site in
    each event, needed for the PML of each site.
    """
    calc = ImpactCalc(exposures, impact_function_set(), hazard)
    return calc.impact(save_mat=True, assign_centroids=False)


def risk_metrics(
    impact: Impact,
    site_ids: Sequence[str],
    return_periods: Sequence[int] = RETURN_PERIODS_YEARS,
) -> RiskMetrics:
    """Derive AAL and PML for each site and for the portfolio from a CLIMADA ``Impact``.

    The portfolio PML is read on the loss of the whole portfolio in each event (``at_event``),
    not summed over sites: sites are rarely flooded in the same years, so site PMLs do not add
    up. AAL does add up.

    Args:
        impact: result of ``compute_impact``.
        site_ids: identifier of each site, in exposure order.
        return_periods: return periods in years, already checked with ``check_return_periods``.
    """
    local, _, _ = impact.local_exceedance_impact(return_periods=return_periods, method=PML_METHOD)
    sites = pd.DataFrame({"site_id": list(site_ids), "aal": impact.eai_exp})
    for rp in return_periods:
        sites[f"pml_{rp}"] = local[str(rp)].to_numpy()

    curve = impact.calc_freq_curve().interpolate(return_periods, method=PML_METHOD)
    portfolio_pml = {rp: float(loss) for rp, loss in zip(return_periods, curve.impact, strict=True)}
    return RiskMetrics(
        sites=sites, portfolio_aal=float(impact.aai_agg), portfolio_pml=portfolio_pml
    )

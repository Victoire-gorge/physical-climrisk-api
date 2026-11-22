# 005. Loss metrics: AAL and empirical PML at 10, 50, 100 and 250 years

## Context
The service reports, for each site and for the portfolio, the average annual loss (AAL) and the
probable maximum loss (PML) at a few return periods. CLIMADA computes the loss of each site in
each event (`Impact.imp_mat`); the metrics are read from it.

Measured on the Gironde river flood set:
- 920 events, each one simulated year (46 models x 20 years, 1980 to 1999), frequency 1/920 each.
  A return period therefore reads directly in years, up to 920.
- Losses are rare: a highly exposed site is flooded in 17 years out of 920 (about once in 54
  years), so its 10-year loss is 0.
- With its default method (`interpolate`), `Impact.local_exceedance_impact` returns NaN instead
  of 0 for a never flooded site and for return periods shorter than the first loss. It also
  returns NaN beyond the observed range.

## Options
For reading a PML at a return period T:
1. **CLIMADA step function** (`method="stepfunction"`), on each site and on the portfolio: the
   loss exceeded with frequency 1/T, read on the empirical exceedance curve. With equally likely
   years, the 100-year loss is the 9th largest yearly loss out of 920 (920 / 100 = 9.2).
2. **CLIMADA `interpolate`, NaN replaced by 0**: wrong beyond the observed range, where NaN means
   unknown, not zero.
3. **Our own empirical quantile**: simple, but reimplements CLIMADA.

For the return periods: 10, 50, 100 and 250 years, or adding 500.

## Decision
Option 1, with return periods 10, 50, 100 and 250 years (`RETURN_PERIODS_YEARS`).
- 250 years still rests on about 3.7 simulated years beyond it; 500 would rest on 1.8.
- Beyond the simulated years, the step function silently repeats the largest loss.
  `check_return_periods` refuses any return period longer than 1 / smallest event frequency.
- The portfolio PML is read on the portfolio loss of each event (`at_event`), never summed over
  sites. The portfolio AAL is the sum of the site AALs.
- `ImpactCalc.impact(assign_centroids=False)` keeps the matching of `nearest_centroid` (see 004
  and the exposure module).

## Consequences
- A zero in the response means no loss at that return period, never an unknown value.
- The PML is a step function of T: it changes only at observed yearly losses, so close return
  periods can share the same value.
- The 920 years are 46 models simulating the same 20 years, not 920 independent years: the real
  uncertainty is larger than the count suggests. No confidence interval is reported yet.
- Sites flooded in different years make the portfolio PML smaller than the sum of site PMLs.
  This diversification is expected and must not be "corrected" by summing.
- A hazard set with fewer years (480 for the RCP scenarios) still covers 250 years.

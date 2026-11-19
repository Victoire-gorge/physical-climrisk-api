# 003. First hazard: river flood, historical period

## Context
The first version needs one hazard covering the zone (see 002) with enough resolution to tell
sites apart, enough simulated years to estimate 50 and 100 year return periods, and a file small
enough for a laptop, a container and CI. Measurements below were made on the zone's bounding box
with the CLIMADA data API (all datasets are CC-BY 4.0).

## Options
| Hazard dataset | Centroids in zone | Period | 50 / 100 year return periods | Size |
|---|---|---|---|---|
| river_flood, France, 150 arcsec | 1,237 | 1980-2000, 920 model-years; RCP 2.6/6.0/8.5 to 2090 | yes | about 4 MB |
| storm_europe ERA5, Europe, 0.5 deg | 9 | 1980-2010 observed | no (30 years) | 20 MB |
| storm_europe CMIP6, Europe, 50 km at best | 6 | historical and SSP | no | about 30 MB |
| storm_europe WISC, France, 4.4 km | about 1,200 (estimated) | historical, probabilistic | yes | 2.7 GB single file |
| wildfire, France, 150 arcsec | 1,237 (96 ever burnt) | 2001-2020, 20 events | no (20 years) | 0.8 MB |
| coastal flood | not available in the data API | | | |

## Decision
River flood (`river_flood`, France, historical 1980-2000), cropped to the zone.
Windstorms (WISC) come next, once the data pipeline can extract the zone from the 2.7 GB file
with bounded memory. Future scenarios are left for later: same format, one extra parameter.

## Consequences
- Each event has a frequency of 1/920 (46 model combinations x 20 years), so return periods up
  to several hundred years can be estimated.
- Intensity is flood depth in metres on a cell of about 4.6 km x 3.3 km, with a flooded
  `fraction` per cell: this is coarse for a single building and is stated as a limitation.
- The data does not model flood defences, nor estuary or coastal surge.
- CLIMADA core ships no flood impact functions; vulnerability curves are defined from a
  published table (decision to come with the vulnerability step).

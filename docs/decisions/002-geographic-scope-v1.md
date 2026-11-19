# 002. Geographic scope of V1: one zone, Gironde (France)

## Context
The service must deliver a working end-to-end version quickly, on a laptop with 8 GB of RAM.
Hazard data from the CLIMADA data API is published per country; the France files also include
overseas territories (longitudes from -61.8 to 55.8), so a country-wide extent would make any
"site out of zone" check meaningless.

## Options
1. **Whole country**: more coverage, but a much larger extent and larger hazard in memory, and
   the bounding box of the data no longer describes where data actually exists.
2. **Several zones at once**: closer to a real product, but requires tiling, a bounded cache and
   routing of sites to zones before the first feature works.
3. **One zone defined in configuration**: small, fast, and nothing hard-coded.

## Decision
Option 3. The zone is a configuration parameter (a country code to query the data API and a
bounding box to crop the hazard). V1 uses the Gironde department: latitude 44.2 to 45.6,
longitude -1.3 to 0.35.

Why Gironde: a small area (about 10,000 km2) with large rivers (Garonne, Dordogne) and an estuary,
a varied economic fabric (aerospace, logistics and port, industry along the estuary, vineyards),
and river flood data at about 4.6 km x 3.3 km resolution. Measured on the historical river flood
hazard: 1,237 centroids in the zone, 330 of them flooded at least once, so results are
contrasted across sites. Fallback zone if needed: the lower Seine valley.

Rules that keep the scope a parameter, not a constant:
- the "out of zone" check uses the extent of the loaded hazard, read from the data;
- the API reports the covered zone (`GET /v1/hazards` and response metadata);
- the data preparation step downloads what the configuration says.

No multi-zone system is built now.

## Consequences
Generalising to more zones would require:
- loading by tiles with a bounded cache (memory grows with the area served);
- merging per-country files for zones that cross borders;
- vulnerability curves chosen by region (current curves are European);
- recalibrated thresholds (distance to centroid, risk levels);
- new reference results for the regression tests.

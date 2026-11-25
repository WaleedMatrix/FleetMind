# Reading provenance

FleetMind distinguishes simulated readings, manual entry, caller-declared telemetry, and unknown origin. The simulator labels new readings as simulated. A telemetry label is the caller's declaration; FleetMind does not independently authenticate the physical measurement. Manual entry records the submission method and does not verify its original source.

## Reviewing mixed origins

Use the source filter in asset monitoring when comparing readings. A synthetic observation should not be treated as field evidence of a fault. Legacy predictions without provenance stay marked unknown. Earlier predictions without an asset identifier stay unassigned.

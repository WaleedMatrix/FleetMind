# Training data and operating limits

FleetMind's frozen xgboost_v1 classifier was trained on the synthetic AI4I 2020 predictive maintenance benchmark. The stratified training partition contains 8,000 observations and 271 labeled failures. Failures are rare, so training used a positive-class weight of approximately 28.52. The held-out benchmark contains 2,000 observations and 68 labeled failures.

## Generalization and forecasting

Benchmark performance does not establish reliability on a specific facility, operating regime, or manufacturer. Independent site validation is needed before operational use. The model classifies individual readings. It has no validated time-to-failure or remaining-useful-life forecast. AI4I rows should not be treated as repeated readings from identified equipment.

# Scores and alert thresholds

FleetMind stores the XGBoost logistic output as an uncalibrated failure score between zero and one. Use it to understand how the model ranked a reading. The score is not an estimated chance that a machine will fail or an estimate of when failure may occur.

## Frozen alert policy

The model metadata defines three mutually exclusive alert levels. Scores below 0.30 have no alert. Scores from 0.30 up to but excluding 0.60 require review. Scores of 0.60 or higher are high priority. The primary threshold of 0.50 is used for the binary classification field and the main reported classification metrics. Alert severity is a review cue and does not confirm machine condition.

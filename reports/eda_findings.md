# FleetMind — Exploratory Data Analysis Report

**Dataset:** AI4I 2020 Predictive Maintenance  
**Source:** UCI Machine Learning Repository  
**Project:** FleetMind  
**Analysis stage:** Milestone 2

## 1. Executive Summary

This report presents an exploratory analysis of the AI4I 2020 Predictive Maintenance dataset, a synthetic dataset containing 10,000 observations of industrial machine operating conditions.

The analysis identified severe target imbalance, inconsistencies between the overall failure label and failure-mode indicators, nonlinear relationships between operating conditions and failures, and a substantial concentration of heat dissipation failures within a specific dataset sequence region.

These findings inform the feature engineering, validation, and model evaluation strategies for FleetMind.

## 2. Dataset Overview

The dataset contains 10,000 observations and 14 columns.

The primary target is `Machine failure`, a binary indicator representing recorded failure conditions.

The six initial candidate predictors are:

- Product type
- Air temperature
- Process temperature
- Rotational speed
- Torque
- Tool wear

The `UDI` and `Product ID` columns will be excluded from the initial predictive feature set.

The five failure-mode indicators (`TWF`, `HDF`, `PWF`, `OSF`, and `RNF`) will also be excluded to prevent target leakage.

## 3. Data Quality

No missing values or duplicate rows were identified.

Both UDI and Product ID contain 10,000 unique values.

However, 27 observations exhibit inconsistencies between the overall machine failure label and the individual failure-mode indicators:

- Nine observations have `Machine failure = 1` without an active failure-mode indicator.
- Eighteen observations have `Machine failure = 0` despite an active RNF indicator.

The original labels will be preserved for baseline modeling. The influence of these inconsistencies may be investigated through sensitivity analysis.

## 4. Class Imbalance

The target distribution is:

| Machine state | Observations | Percentage |
|---|---:|---:|
| Normal | 9,661 | 96.61% |
| Failure | 339 | 3.39% |

A majority-class classifier would achieve 96.61% accuracy while detecting no failures.

Consequently, accuracy alone is insufficient for model evaluation.

Primary evaluation metrics will include average precision (PR-AUC summary), recall, precision, F1-score, and confusion matrices.

False-positive and false-negative trade-offs will also be examined.

## 5. Feature Relationships

Two strong linear correlations were identified:

| Feature pair | Pearson correlation |
|---|---:|
| Air temperature / Process temperature | +0.8761 |
| Rotational speed / Torque | −0.8750 |

Other numerical feature pairs exhibited relatively weak linear correlations.

These relationships motivate investigation of physically meaningful engineered features rather than automatic feature removal.

## 6. Tool Wear and Failure

The observed failure rate increased substantially in the highest tool-wear interval.

| Tool wear (minutes) | Failure rate |
|---|---:|
| 0–49 | 2.21% |
| 50–99 | 2.25% |
| 100–149 | 2.27% |
| 150–199 | 2.66% |
| 200–253 | 15.36% |

This suggests a nonlinear association between accumulated wear and machine failure.

The observed interval boundaries will not be treated as validated predictive thresholds.

## 7. Mechanical Power

Mechanical power was derived from rotational speed and torque.

Failed observations had higher mean mechanical power than normal observations:

- Normal: 6.245 kW
- Failure: 7.283 kW

Failure rates varied nonlinearly across power deciles.

The highest power decile exhibited a 16.9% failure rate, while the lowest decile exhibited a 4.0% failure rate.

This indicates that failures may occur under multiple operating regimes.

## 8. Thermal Conditions

The temperature difference between process and air temperature was examined as a candidate engineered feature.

Heat dissipation failure observations had:

- Mean air temperature: 302.561 K
- Mean process temperature: 310.789 K
- Mean temperature difference: 8.228 K

Non-HDF observations had a mean temperature difference of 10.021 K.

The observed HDF cases were concentrated in a region characterized by elevated air temperatures and relatively small temperature differences.

These associations are consistent with the synthetic dataset's thermal failure mechanism but do not independently establish causality.

## 9. Dataset Sequence Anomaly

Sequence group 5, representing UDI values 4001–5000, contained:

- 1,000 observations
- 134 overall failures
- 108 HDF indicators
- A 13.4% overall failure rate

This group accounted for approximately 39.5% of all recorded failures and 93.9% of HDF indicators.

Group 6 had a similar mean air temperature but a larger mean process-to-air temperature difference and no recorded HDF indicators.

This supports the hypothesis that combined thermal conditions explain much of the observed concentration.

Because UDI is not a verified timestamp, sequence-based analysis must not be interpreted as direct evidence of chronological machine degradation.

## 10. Modeling Implications

FleetMind's initial modeling experiments will:

1. Preserve the original binary failure target.
2. Exclude identifiers and failure-mode indicators from model inputs.
3. Compare original operational features against physically derived features.
4. Use stratified evaluation for initial benchmarking.
5. Supplement conventional evaluation with sequence-blocked robustness testing.
6. Fit learned preprocessing exclusively on training data.
7. Evaluate minority-class detection rather than relying on accuracy.
8. Avoid selecting feature thresholds using final test-set performance.

Candidate engineered features include temperature difference, mechanical power, and torque–wear interaction.

## 11. Limitations

The AI4I dataset is synthetic and may contain deterministic or near-deterministic failure-generation rules.

It does not provide verified future failure horizons, machine-level longitudinal histories, or remaining useful life labels.

Consequently, FleetMind's initial binary model will classify recorded failure conditions rather than provide validated forecasts of future failure timing.

The evaluation results should not be interpreted as evidence of real-world deployment performance without external validation.

## 12. Conclusion

The exploratory analysis identified significant class imbalance, structured thermal failure behavior, nonlinear mechanical relationships, and sequence-dependent distribution patterns.

These findings justify careful feature engineering, leakage prevention, and multiple evaluation protocols.

The next milestone will establish reproducible baseline models and evaluate their ability to detect rare failure observations under clearly documented assumptions.

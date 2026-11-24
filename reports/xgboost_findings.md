# FleetMind — XGBoost, Blocked Validation, and Thermal Feature Engineering

**Experiment status:** Development analysis; not an independent performance estimate  
**Dataset:** UCI AI4I 2020 (synthetic machine-failure classification)  
**Report date:** 2026-11-21  
**Suggested repository location:** `reports/xgboost_findings.md`

## Executive summary

XGBoost is FleetMind's leading development-stage model. A baseline XGBoost pipeline achieved **0.7472 ± 0.0325 mean average precision (AP)** and **0.6536 ± 0.0303 mean F1** under five-fold stratified randomized cross-validation. A more demanding UDI-group-blocked evaluation reduced baseline XGBoost's mean AP to **0.6001**, exposing a generalization weakness involving the HDF-heavy UDI 4001–5000 region.

Adding one physically motivated feature, **temperature gap = process temperature − air temperature**, improved mean AP to **0.6943** and mean F1 to **0.5851** across the five blocked folds. Pooled out-of-fold results improved from **148 true positives / 212 false positives** to **177 true positives / 160 false positives**, detecting **29 additional failures with 52 fewer false alarms** at threshold 0.5.

A threshold sweep showed that **0.6 had the highest pooled F1 (0.5934) among the tested thresholds**, while lower thresholds increased failure detection at the cost of false alarms. The final operating threshold remains a product/operational decision and has **not yet been independently validated**.

## 1. Data, task, and leakage safeguards

- AI4I 2020 has 10,000 synthetic observations; target: `Machine failure` (binary); overall failure prevalence: 339/10,000 = 3.39%.
- Original stratified development/test split: 8,000 development observations (271 failures) and 2,000 held-out test observations (68 failures). The held-out test partition has **not been used** in these model-selection and robustness experiments.
- Model inputs: `Type`, `Air temperature [K]`, `Process temperature [K]`, `Rotational speed [rpm]`, `Torque [Nm]`, and `Tool wear [min]`; the enhanced model also derives `Temperature gap [K]` from the two temperature measurements.
- `UDI` is used exclusively to define diagnostic and validation groups, not as a predictor. `Product ID` and failure-mode/outcome columns (`TWF`, `HDF`, `PWF`, `OSF`, `RNF`) are excluded from model training. Failure-mode columns are used only for post-hoc error analysis.
- This dataset labels failure states in synthetic observations. Results **do not prove future failure forecasting**, remaining-useful-life estimation, or real-factory reliability.

## 2. XGBoost model specification

The XGBoost pipeline applies a `ColumnTransformer` with numerical pass-through and one-hot encoding of `Type`, then an `XGBClassifier` with:

| Hyperparameter | Value |
|---|---|
| `n_estimators` | 300 |
| `max_depth` | 4 |
| `learning_rate` | 0.05 |
| `subsample` | 0.8 |
| `colsample_bytree` | 0.9 |
| `objective` | `binary:logistic` |
| `eval_metric` | `logloss` |
| `tree_method` | `hist` |
| `random_state` | 42 |
| `scale_pos_weight` | Negatives / positives, computed from **each fit partition only** |

The enhanced pipeline additionally calculates `Temperature gap [K] = Process temperature [K] − Air temperature [K]` via the pipeline feature-engineering transform. The baseline and enhanced configurations otherwise share these hyperparameters.

## 3. Initial validation: 6,400 fit / 1,600 validation

The original XGBoost baseline (without thermal gap) produced:

| Metric | Baseline XGBoost |
|---|---:|
| Accuracy | 0.9650 |
| Average precision | 0.7591 |
| Precision at 0.5 | 0.4884 |
| Recall at 0.5 | 0.7778 |
| F1 at 0.5 | 0.6000 |
| Confusion matrix `[[TN, FP], [FN, TP]]` | `[[1502, 44], [12, 42]]` |
| Fitting `scale_pos_weight` | 28.49 |

For comparison on this same validation partition, Random Forest achieved AP 0.6518 and F1 0.5655; logistic regression achieved AP 0.4197 and F1 0.2453. These are exploratory single-split comparisons.

## 4. Five-fold randomized cross-validation: original model candidates

Means and population standard deviations across five stratified folds of the original 8,000-observation development partition:

| Model | Mean AP | AP std | Mean precision | Mean recall | Mean F1 | F1 std |
|---|---:|---:|---:|---:|---:|---:|
| Logistic regression | 0.4409 | 0.0299 | 0.1374 | 0.8044 | 0.2346 | 0.0100 |
| Random Forest | 0.7104 | 0.0339 | 0.5047 | 0.8043 | 0.6198 | 0.0157 |
| XGBoost | **0.7472** | 0.0325 | **0.5446** | **0.8193** | **0.6536** | 0.0303 |

XGBoost performed best among these models on all four mean classification metrics shown. These folds randomize observations across the UDI sequence, so they do not test whether performance generalizes to unseen UDI regions.

## 5. Sequence-blocked robustness evaluation

Ten diagnostic UDI groups were defined using `((UDI - 1) // 1000)`; five-fold `GroupKFold` excluded two entire groups from fitting in each fold. UDI ordering is **not verified to be chronological**, so this is a blocked distribution-shift stress test—not temporal validation.

| Model | Mean blocked AP | AP std (sample) | Mean precision | Mean recall | Mean F1 |
|---|---:|---:|---:|---:|---:|
| Random Forest | 0.5105 | 0.1319 | 0.3964 | 0.6541 | 0.4584 |
| Baseline XGBoost | **0.6001** | 0.0768 | **0.4360** | 0.6331 | **0.4869** |

The discrepancy between randomized and blocked scores suggests sensitivity to data-region shifts. Mean fold AP should be read alongside each fold's prevalence, because AP baselines change with class prevalence.

### High-failure region: group 4 (UDI 4001–5000)

In the original 8,000-observation development partition:

- Group 4 contained **802 observations**, **105 labeled failures** (**13.09% failure rate**), and **81 HDF indicators**.
- It accounted for **105/271 = 38.7%** of all development-partition failures despite containing roughly 10% of the observations.
- In the blocked fold holding out groups 4 and 8, the fitting data contained only **five HDF-labeled failures**.
- In group 4 alone, baseline XGBoost detected **30/105 failures**, missed **75**, and raised **15 false alarms**; **68 of its missed failures** were HDF-labeled.
- On the 81 group-4 HDF-labeled failures, baseline XGBoost flagged **13/81 (16.05%)** at threshold 0.5. Its median HDF prediction score was **0.0465**.

This supports the hypothesis that scarce examples of one failure mode create an out-of-region detection challenge. It does not prove a causal mechanism, and individual model scores are not calibrated probabilities.

## 6. One-feature experiment: thermal gap

A controlled experiment kept the blocked folds, model hyperparameters, and training-fold class weights fixed and toggled only the temperature-gap feature.

### Mean metrics across blocked folds

| Metric | Baseline XGBoost | XGBoost + thermal gap | Absolute change |
|---|---:|---:|---:|
| Mean AP | 0.6001 | **0.6943** | +0.0942 |
| Mean precision | 0.4360 | **0.5141** | +0.0781 |
| Mean recall | 0.6331 | **0.7118** | +0.0787 |
| Mean F1 | 0.4869 | **0.5851** | +0.0982 |
| Group-4 HDF recall in its held-out fold | 0.1605 | **0.4198** | +0.2593 |

Per-fold AP improved for all five blocked folds:

| Held-out UDI groups | Baseline AP | Thermal-gap AP |
|---|---:|---:|
| [6, 7] | 0.6209 | **0.7018** |
| [3, 9] | 0.5960 | **0.7163** |
| [1, 2] | 0.7072 | **0.7284** |
| [0, 5] | 0.5830 | **0.6767** |
| [4, 8] | 0.4936 | **0.6483** |

### Pooled out-of-fold confusion-matrix counts (threshold 0.5)

| Measure | Baseline | Thermal gap | Change |
|---|---:|---:|---:|
| True positives (TP) | 148 | **177** | +29 |
| False positives (FP) | 212 | **160** | −52 |
| False negatives (FN) | 123 | **94** | −29 |
| True negatives (TN) | 7,517 | **7,569** | +52 |
| Alerts (TP + FP) | 360 | **337** | −23 |
| Pooled precision | 0.4111 | **0.5252** | +0.1141 |
| Pooled recall | 0.5461 | **0.6531** | +0.1070 |
| Pooled F1 | 0.4691 | **0.5822** | +0.1131 |

**Important distinction:** Mean fold metrics equally weight the five folds; pooled metrics aggregate out-of-fold classifications across all 8,000 development observations. The blocked folds have uneven failure counts. These pooled counts are produced by **five separate fitted models**, not a single deployed estimator.

### Especially difficult held-out fold: groups 4 and 8

| Measure | Baseline | Thermal gap |
|---|---:|---:|
| TP | 38 | **59** |
| FP | 33 | 34 |
| FN | 79 | **58** |
| TN | 1,450 | 1,449 |
| Precision | 0.5352 | **0.6344** |
| Recall | 0.3248 | **0.5043** |
| F1 | 0.4043 | **0.5619** |
| Group-4 HDF detected | 13/81 | **34/81** |

The engineered model found **21 additional HDF-labeled failures** in group 4, with one additional false alarm in the combined blocked fold. It still missed **47 of the 81** HDF-labeled cases.

## 7. Alert-threshold exploration

Thresholds were applied to **out-of-fold scores** produced by the thermal-gap XGBoost pipeline under the same five UDI-blocked folds.

| Threshold | Precision | Recall | F1 | TP | FP | FN | Alerts | Group-4 HDF recall |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.1 | 0.2716 | 0.8819 | 0.4153 | 239 | 641 | 32 | 880 | 0.8519 |
| 0.2 | 0.3443 | 0.8118 | 0.4835 | 220 | 419 | 51 | 639 | 0.7531 |
| 0.3 | 0.4064 | 0.7454 | 0.5260 | 202 | 295 | 69 | 497 | 0.6173 |
| 0.4 | 0.4738 | 0.7011 | 0.5655 | 190 | 211 | 81 | 401 | 0.5062 |
| 0.5 | 0.5252 | 0.6531 | 0.5822 | 177 | 160 | 94 | 337 | 0.4198 |
| **0.6** | **0.5891** | 0.5978 | **0.5934** | 162 | 113 | 109 | 275 | 0.3704 |
| 0.7 | 0.6460 | 0.5387 | 0.5875 | 146 | 80 | 125 | 226 | 0.2346 |
| 0.8 | 0.7257 | 0.4686 | 0.5695 | 127 | 48 | 144 | 175 | 0.1852 |
| 0.9 | 0.9008 | 0.4022 | 0.5561 | 109 | 12 | 162 | 121 | 0.1235 |

Threshold **0.6 achieved the highest F1 of these nine tested points**; this is *not* proof it is the best business threshold or the continuous F1 optimum. In maintenance, false negatives and false positives may have significantly different costs. Threshold 0.3 detects 40 more failures than 0.6 but also produces 182 additional false alarms.

### Candidate two-tier policy (not validated)

- **High-priority alert:** score >= 0.6. In the blocked OOF exercise, 275 alerts: 162 TP and 113 FP.
- **Lower-priority inspection review:** 0.3 <= score < 0.6. Adds 222 alerts: 40 TP and 182 FP.
- **No automatic alert:** score < 0.3. This set still includes 69 missed failures.

These thresholds are exploratory. The class-weighted XGBoost score should not be presented as a calibrated failure probability, and the proposal does not include real maintenance costs or equipment safety requirements.

## 8. Interpretation, threats to validity, and next steps

1. **Keep the engineered model as the leading development candidate.** It improved AP on every evaluated blocked fold and improved both pooled failure detection and false-alarm counts at threshold 0.5.
2. **Avoid claiming unbiased validation for the feature.** The thermal-gap idea emerged after inspecting blocked-fold errors. Those same folds were then used to measure its performance; the improvement is promising but subject to model-development selection bias.
3. **Freeze the model and the operating policy before final evaluation.** If the eventual business objective isn't specified, report a predeclared reference threshold (e.g., 0.5) and optionally a separately predeclared operating policy; avoid selecting the final threshold after examining test labels.
4. **Evaluate the original untouched 2,000-observation test set only once**, after freezing feature engineering, hyperparameters, and threshold policy. Train the selected pipeline on all 8,000 development observations; calculate `scale_pos_weight` only from those fitting labels. Report AP, confusion matrix, precision, recall, F1, and alert counts.
5. **Interpret the test correctly.** The test set is a random stratified sample of the same synthetic dataset, not an unseen-region or future-in-time test. A strong test score will not resolve the distribution-shift limitations revealed by the blocked experiment.
6. **Future work:** Inspect score calibration using development-only data; compare threshold policies using stated miss/inspection costs; assess further robustness on independent equipment or datasets; create documented inference and monitoring interfaces.

## 9. Reproducibility

Run from the repository root, with the project virtual environment activated:

```powershell
python scripts/run_xgboost_baseline.py
python scripts/run_xgboost_cross_validation.py
python scripts/run_blocked_validation.py
python scripts/analyze_udi_groups.py
python scripts/analyze_blocked_errors.py
python scripts/analyze_hdf_scores.py
python scripts/compare_thermal_feature.py
python scripts/analyze_xgboost_alert_thresholds.py
python -m pytest
python -m ruff check src tests scripts
```

Latest shared validation state: **seven tests passed**, Ruff **all checks passed**.

---

**Portfolio-ready conclusion:** On the synthetic AI4I dataset's development partition, adding process-to-air temperature difference to an XGBoost pipeline improved mean UDI-blocked average precision from 0.6001 to 0.6943. Across five out-of-fold blocked evaluations at score threshold 0.5, it detected 29 more labeled failures while generating 52 fewer false positives. The result supports the value of physics-informed feature representation but remains a development-stage finding pending a frozen, held-out evaluation and external validation.

# FleetMind — Random Forest Baseline Findings

**Project:** FleetMind — Machine Failure Classification  
**Dataset:** AI4I 2020 Predictive Maintenance (UCI; synthetic)  
**Experiment:** Random Forest baseline, five-fold stratified cross-validation, and permutation importance  
**Status:** Completed on training-only development partitions; final held-out evaluation pending

## 1. Executive summary

A Random Forest classifier substantially outperformed the logistic regression baseline in **average precision, precision, and F1-score** on the AI4I synthetic machine-failure classification task. In five-fold stratified cross-validation, Random Forest achieved **0.7104 ± 0.0339 average precision** and **0.6198 ± 0.0157 F1**, versus **0.4409 ± 0.0299 average precision** and **0.2346 ± 0.0100 F1** for logistic regression. Mean recall was almost identical: **0.8043** versus **0.8044**, respectively.

On the original training-only validation split (1,600 observations; 54 failures), Random Forest identified **41 failures**, missed **13**, and generated **50 false alarms** at the default classification threshold. Logistic regression identified **46 failures**, missed **8**, and generated **275 false alarms** on that same split. Thus, Random Forest made far fewer false-positive predictions but missed five more failures at the respective default thresholds.

Permutation importance using **average precision** indicated that the fitted Random Forest relied most heavily on **torque**, **rotational speed**, and **tool wear**. These are associations with model predictions, not evidence of causation.

## 2. Dataset and evaluation design

- **Dataset:** AI4I 2020, 10,000 synthetic observations.
- **Target:** `Machine failure` (binary); 339 positive cases in the complete dataset (3.39%).
- **Input features:** `Type`, `Air temperature [K]`, `Process temperature [K]`, `Rotational speed [rpm]`, `Torque [Nm]`, and `Tool wear [min]`.
- **Excluded:** `UDI`, `Product ID`, and failure-mode indicators `TWF`, `HDF`, `PWF`, `OSF`, `RNF`. The failure-mode indicators are outcomes and could introduce target leakage.
- **Initial split:** Stratified 80/20 with `random_state=42`: 8,000 training observations (271 failures) and 2,000 held-out test observations (68 failures).
- **Single validation experiment:** Training partition split again into 6,400 fitting observations and 1,600 validation observations (54 failures), stratified with `random_state=42`.
- **Cross-validation:** Five-fold `StratifiedKFold(n_splits=5, shuffle=True, random_state=42)` on the **8,000-observation training partition only**. The estimator is refitted independently for each fold.
- **Held-out test set:** Not used to compare or select trained models; reserved for final evaluation. An earlier instructional dummy-classifier sanity check did report test metrics, but no trained-model selection has used the test set.

## 3. Model configuration

Implemented in `src/fleetmind/models/random_forest.py` as a scikit-learn `Pipeline`:

| Component | Configuration |
|---|---|
| Numerical preprocessing | Passthrough for the five numerical features |
| Categorical preprocessing | `OneHotEncoder(handle_unknown="ignore")` for `Type` |
| Estimator | `RandomForestClassifier` |
| `n_estimators` | 200 |
| `max_depth` | 12 |
| `min_samples_leaf` | 3 |
| `class_weight` | `"balanced"` |
| `random_state` | 42 |
| `n_jobs` | -1 |

The preprocessing transformer and classifier are encapsulated in one pipeline, so categorical encoding is fitted within each training fold. Numerical scaling is unnecessary for tree splits. These are initial baseline hyperparameters, **not** a result of a documented hyperparameter search.

## 4. Single-split validation results

Both models were evaluated on the same 1,600-observation validation partition.

| Metric | Logistic regression | Random Forest |
|---|---:|---:|
| Accuracy | 0.823125 | **0.960625** |
| Precision | 0.143302 | **0.450549** |
| Recall | **0.851852** | 0.759259 |
| F1-score | 0.245333 | **0.565517** |
| Average precision | 0.419706 | **0.651844** |
| True positives | **46** | 41 |
| False positives | 275 | **50** |
| False negatives | **8** | 13 |
| True negatives | 1,271 | **1,496** |

**Random Forest confusion matrix**, with rows representing actual class `[normal, failure]` and columns representing predicted class `[normal, failure]`:

```text
[[1496,  50],
 [  13,  41]]
```

At the default 0.5 threshold, the model issued **91 alerts**, of which **41 were correct** (45.05% precision). It detected **41 of 54** actual failures (75.93% recall).

Compared with logistic regression on this split, Random Forest reduced false positives from 275 to 50 (**81.8% fewer**), but increased missed failures from 8 to 13. A lower false-alarm count should not be interpreted as an unconditional operational improvement without defining the relative costs of missed failures and false alerts.

## 5. Five-fold stratified cross-validation

Reported values are the arithmetic mean and population standard deviation of the five fold-level metrics (`numpy.std()` default, `ddof=0`).

| Metric | Logistic regression mean | Logistic regression std | Random Forest mean | Random Forest std |
|---|---:|---:|---:|---:|
| Average precision | 0.4409 | 0.0299 | **0.7104** | 0.0339 |
| Precision | 0.1374 | 0.0051 | **0.5047** | 0.0226 |
| Recall | 0.8044 | 0.0668 | 0.8043 | 0.0199 |
| F1-score | 0.2346 | 0.0100 | **0.6198** | 0.0157 |

### Interpretation

- Random Forest's mean average precision exceeded logistic regression by **0.2695 absolute points** (approximately **61.1% relative improvement**).
- Mean precision was approximately **3.67 times** logistic regression's precision at the models' default classification thresholds.
- Mean recall was effectively the same (**80.43%** versus **80.44%**), so the higher precision did not coincide with lower *mean* recall in these five folds.
- Fold-to-fold variation was modest for the reported randomized splits. These standard deviations are **not** confidence intervals and do not establish generalization to new factories, machines, or future periods.
- Precision, recall, and F1 depend on the classification threshold. Average precision summarizes precision-recall ranking performance over score thresholds and is the principal comparison metric for this imbalanced task.

## 6. Permutation feature importance

Permutation importance was calculated on the **1,600-observation validation partition** using the Random Forest fitted to the corresponding **6,400-observation fitting partition**, with `scoring="average_precision"`, `n_repeats=10`, and `random_state=42`.

| Rank | Feature | Mean decrease in average precision | Std across permutations |
|---:|---|---:|---:|
| 1 | `Torque [Nm]` | **0.4099** | 0.0270 |
| 2 | `Rotational speed [rpm]` | **0.3006** | 0.0308 |
| 3 | `Tool wear [min]` | **0.2000** | 0.0185 |
| 4 | `Air temperature [K]` | **0.1905** | 0.0415 |
| 5 | `Process temperature [K]` | **0.1236** | 0.0373 |
| 6 | `Type` | **0.0667** | 0.0265 |

**Interpretation:** Shuffling torque lowered average precision by about **0.4099** on average, suggesting the fitted model depends strongly on that feature for ranking failure cases. Rotational speed and tool wear were also important. These values represent **drops in average precision**, not percentages of total importance; they should not be summed or interpreted as causal contributions.

**Important caveat:** Air temperature and process temperature are strongly correlated in this dataset (approximately **r = 0.876** in the EDA). Permutation importance can understate or redistribute the apparent contribution of correlated predictors. Rankings also reflect this particular fitted model and validation split; they may vary across folds or under distribution shift.

## 7. Relationship to exploratory findings

The results are consistent with several earlier EDA observations:

- Failure cases clustered in regions of the rotational-speed/torque feature space, including high-torque/low-speed operation.
- Tool-wear values in the highest observed bin were associated with elevated failure frequency.
- Temperature patterns, including the difference between process and air temperatures, were associated with heat-dissipation failure indicators.

These observations provide plausible explanations for why a nonlinear tree ensemble outperforms a linear baseline, **but this experiment does not isolate which interactions account for the performance difference**. Feature engineering, partial-dependence or accumulated-local-effects analysis, and further validation would be needed to examine the relationships more carefully.

## 8. Limitations and risks

1. **Synthetic dataset:** AI4I simulates machine operating conditions and failure labels. The task is classification of contemporaneous failure states, not a demonstrated prediction of failures hours or days ahead. No validated forecast horizon or remaining-useful-life target is available here.
2. **Sequence concentration:** Earlier EDA found 134 of 339 failures in UDI rows 4001–5000, with a high concentration of HDF indicators. Randomized folds may share similar synthetic regimes across fitting and validation partitions and overstate robustness to regime changes. `UDI` is not a verified timestamp.
3. **Label discrepancies:** EDA identified 27 rows where `Machine failure` and failure-mode indicators do not align. Labels were retained as provided; sensitivity analysis is pending.
4. **Threshold sensitivity:** The default 0.5 threshold is not an operationally optimized alert policy. Weighted classifiers' score outputs should not automatically be treated as calibrated probabilities.
5. **Limited uncertainty assessment:** Five stratified folds provide useful internal consistency evidence, but are not a substitute for grouped, blocked, or genuinely external validation.
6. **No final test result:** The 2,000-observation held-out test set remains reserved for final model evaluation after model and threshold selection.

## 9. Reproducibility and verification

Relevant project files:

```text
src/fleetmind/data/split.py
src/fleetmind/models/logistic.py
src/fleetmind/models/random_forest.py
src/fleetmind/evaluation/validation.py
scripts/run_random_forest_baseline.py
scripts/run_cross_validation.py
scripts/analyze_feature_importance.py
tests/unit/test_random_forest.py
```

Commands used:

```powershell
python scripts/run_random_forest_baseline.py
python scripts/run_cross_validation.py
python scripts/analyze_feature_importance.py
python -m pytest
python -m ruff check src tests scripts
```

**Verification:** The latest reported run passed **5/5 pytest tests**, and Ruff reported **“All checks passed!”**. These checks verify the existing tested behavior and linting; they do not independently validate every scientific inference in this report.

## 10. Recommended next steps

1. Train and evaluate an XGBoost baseline on the same training-only development split.
2. Compare XGBoost and Random Forest with fold-specific imbalance handling and stratified cross-validation.
3. Run a sequence-blocked robustness evaluation to test sensitivity to synthetic operating regimes and the concentrated failure region.
4. Examine threshold selection, alert burden, and probability calibration using training-only validation predictions.
5. Conduct label-discrepancy sensitivity checks and consider engineered features such as thermal gap and mechanical power.
6. Freeze the selected pipeline and decision rule, then evaluate once on the untouched held-out test set.

## 11. Conclusion

**Random Forest is the leading FleetMind baseline under randomized training-only evaluation.** It achieved substantially higher average precision and F1 than logistic regression, with comparable cross-validated recall and markedly higher precision. Permutation importance suggests substantial predictive reliance on torque, rotational speed, and tool wear. The next priority is to test whether these gains persist under more demanding validation schemes before claiming generalization beyond the AI4I synthetic dataset.

# Model card — XGBoost v1

FleetMind scores a single AI4I-style machine reading for a binary failure label. Inputs are machine type (L, M, H), air and process temperature (K), rotational speed (rpm), torque (N·m), and tool wear (min). The fitted pipeline encodes machine type and calculates thermal gap as process minus air temperature. Inference verifies artifact digests and uses the exact fitted preprocessing and XGBoost classifier.

~~~mermaid
flowchart LR
  A["AI4I 10,000 synthetic rows"] --> B["80/20 stratified split"]
  B --> C["8,000 training rows / cross-validation"]
  C --> D["Fitted preprocessing and XGBoost"]
  B --> E["2,000 held-out rows"]
  D --> E
  D --> F["Frozen inference and TreeSHAP"]
  E --> G["Held-out evaluation report"]
~~~

The full data contains 339 labelled failures (3.39%). The 8,000 training rows contain 271 failures. Training used a positive-class weight of 28.5203. See the [experiment findings](../reports/xgboost_findings.md), [held-out report](../reports/final_test_metrics.json) and [source notebooks](../notebooks/).

| Held-out metrics | Value |
| --- | ---: |
| Average precision | 0.8655 |
| Precision at the selected 0.50 threshold | 0.5842 |
| Recall at 0.50 | 0.8676 |
| F1 at 0.50 | 0.6982 |
| TP / FP / FN / TN | 59 / 42 / 9 / 1,890 |

Review begins at 0.30 and high priority at 0.60. The binary label threshold is 0.50. The output is an uncalibrated failure score on synthetic observations. The dataset supports neither a validated maintenance forecast nor an equipment-specific time-to-failure estimate. The portfolio assets represent fictional devices and replayed simulator inputs. Check operator evidence and get qualified human confirmation before acting.

TreeSHAP explains the pre-sigmoid raw margin. Signed values plus baseline recover the raw model output within numerical tolerance. Categorical contributions are grouped across the fitted encoding. Contributions depend on the model and correlated inputs. They quantify model attribution and cannot establish causation. Global mean absolute SHAP uses 512 training rows sampled at seed 42, with the original preprocessing. [Global report](../reports/global_shap_xgboost_v1.json) · [Sensor units](knowledge/sensor-reference.md) · [SHAP interpretation](knowledge/shap-explanations.md)

Model Health compares current, source-scoped inputs with the historical training distribution using PSI and Jensen–Shannon divergence. Sparse windows withhold indicators. Drift indicates a distribution change. Quantifying a change in predictive performance would require verified outcome labels. [Monitoring methodology](mlops.md)

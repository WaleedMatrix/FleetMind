# FleetMind technical case study

FleetMind starts with a machine reading and follows it through classification, attribution, evidence retrieval, and human review. The project uses a small synthetic dataset to study a complete applied ML system, including where the available evidence stops.

## Choosing and freezing the model

The dataset has 339 labelled failures among 10,000 synthetic rows. Accuracy alone would obscure failure recall. The experiments compare logistic regression, random forest, and gradient boosting with average precision as the primary ranking measure. The selected XGBoost pipeline uses a thermal gap and class weighting, and stores the fitted encoder with the classifier. On the untouched 2,000-row holdout it reached AP 0.8655. At score 0.50 it flagged 101 observations, including 59 true positives and 42 false positives, and missed nine of the 68 labelled failures. The threshold and higher-priority tier provide review signals. They do not estimate calibrated risk.

## Making an alert inspectable

SQLite and PostgreSQL fixtures preserve original values so explanations use the same trained preprocessing and model version. Local TreeSHAP contributions are grouped for machine type and reconcile to the raw model margin. Global SHAP summarizes a seeded sample of 512 training rows. Version or artifact mismatches yield an unavailable explanation. In Model Health, source-scoped comparisons reveal shifts while sparse windows withhold drift indicators.

## Connecting inference and storage

The Redpanda worker validates each envelope and confirms asset type before scoring. The database commits first. The broker offset is acknowledged after durable processing and a unique event ID makes replays idempotent. Dead-letter handling stores bounded diagnostics for permanently invalid inputs. The SSE read model sends only committed events using a resumable cursor. At target 60 events/s, the paired two-worker run achieved 41.6 committed/s with 6.38 s p95 observed-to-commit latency. It was limited by the local workload and resource shape.

## Keeping evidence and cost bounded

PostgreSQL full-text ranking and pgvector ranking meet through reciprocal rank fusion. Copilot constrains tool selection and request deadlines, validates source references, and abstains on unsupported questions. The 51 scripted cases exercise deterministic execution and evidence checks. A separate evaluation with an authorized live provider remains pending. The paired browser recording cut desktop long tasks from eight to one while sampled heap increased from 9.92 to 17.07 MiB. Both measurements matter to the streaming UI tradeoff.

The public portfolio bundles scored simulator examples, SHAP, and scripted Copilot responses. Its optional Render inference service is independent of the local authenticated application, ownership model, database and workers. The site can be reviewed even when the endpoint sleeps. Some scientific and operational questions remain open, including real equipment generalization, score calibration, labelled drift impact, production throughput and cloud availability.

[Held-out report](../reports/final_test_metrics.json) · [Experiment notes](../reports/xgboost_findings.md) · [Performance methods](mlops.md) · [Deployment](deployment.md)

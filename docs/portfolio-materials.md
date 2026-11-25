# Portfolio materials

## Project description

FleetMind is an end-to-end machine monitoring and investigation portfolio project. It connects frozen XGBoost inference, model-version-checked SHAP, event-driven PostgreSQL persistence, and a cited maintenance Copilot. A read-only public profile demonstrates the workflows with labelled simulation and scripted examples.

## Résumé bullets

- Trained and froze a class-weighted XGBoost pipeline for 10,000 synthetic AI4I observations with 3.39% failure prevalence, reaching 0.8655 average precision and 0.8676 recall at the selected threshold on a 2,000-row holdout.
- Implemented model-version-checked TreeSHAP investigation and global attribution across 512 seeded training rows, using the same fitted feature transformation as inference.
- Built an at-least-once Redpanda ingestion path with database idempotency and resumable SSE. The two-worker local test committed 41.6 assessments/s with 6.38 s p95 observation-to-commit latency at the recorded workload.
- Built hybrid PostgreSQL retrieval and typed Copilot evidence checks that passed 51 deterministic cases covering tool routing, citation integrity, and abstention.
- Reduced paired desktop telemetry browser long tasks from 8 to 1, with a measured sampled heap increase from 9.92 to 17.07 MiB.

[Model evaluation](../reports/final_test_metrics.json) · [SHAP sample](../reports/global_shap_xgboost_v1.json) · [Copilot results](../reports/copilot_scripted_m11b.json) · [Benchmark methods](mlops.md)

## LinkedIn draft

I built FleetMind to explore what it takes to carry a machine assessment from sensor input to evidence a reviewer can inspect. It combines a frozen XGBoost pipeline, TreeSHAP, asset history, committed telemetry over SSE, and a maintenance Copilot that cites its sources.

On the synthetic AI4I holdout, the model reached 0.8655 average precision. A two-worker local telemetry benchmark committed 41.6 assessments per second. The application labels synthetic inputs and exposes the limits of the score and explanations.

The portfolio edition demonstrates these workflows with recorded assessments and scripted Copilot examples. I’ll add the demo and repository links after release validation.

## Two-minute demo script

| Time | On screen and narration |
| --- | --- |
| 0:00–0:20 | Dashboard. “FleetMind turns an individual reading into an assessment you can inspect. All displayed portfolio readings are simulated.” |
| 0:20–0:40 | Alert drawer, then SHAP. “The raw inputs, model version and score are saved together. SHAP shows what moved the raw margin.” |
| 0:40–1:00 | Asset detail and replay. “A worker validates asset identity, saves assessments idempotently, and streams committed changes. This view replays a recorded sequence.” |
| 1:00–1:18 | Model Intelligence and Health. “The held-out average precision is 0.8655. Health compares source-scoped distributions to a training reference.” |
| 1:18–1:38 | Copilot example and citation. “This is a scripted example from the test harness. The full local app validates evidence and abstains when sources are insufficient.” |
| 1:38–2:00 | Architecture. “The public frontend runs without a database or a paid model account. Optional CPU inference scores selected readings without persisting them.” |

## Interview walkthrough

1. Explain data provenance, the stratified split, average precision, the selected threshold, and the 42 false positives.
2. Open an alert. Tie the immutable inputs and verified model version to the grouped SHAP raw-margin reconciliation.
3. Trace event delivery through the commit/ack failure window and show why the unique source ID matters.
4. Explain retrieval fusion, evidence validation, owner-scoped streaming, and the limits of scripted tests.
5. Compare the two deployment profiles, and discuss the tradeoff between preserving the full local workflow and maintaining a stateless free-tier demo.

## Personal portfolio card

**FleetMind — AI machine monitoring and evidence review**

XGBoost · TreeSHAP · FastAPI · PostgreSQL/pgvector · Redpanda · Next.js

Inspect a real frozen model’s assessments on simulated inputs, replay telemetry, and explore cited maintenance examples.

Actions after validation · **View demo**, **Read case study**, **Source**.

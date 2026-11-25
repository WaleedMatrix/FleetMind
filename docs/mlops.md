# FleetMind MLOps and observability

Milestone 11B adds an operational view for FleetMind’s frozen XGBoost model,
metrics for API and inference processes, and reproducible evaluation tooling.
The operational view and held-out model evaluation answer different questions.
Drift measures distribution changes. Verified outcomes are required to assess
live precision, recall, accuracy, or F1. Maintenance decisions still require
human review.

## Activate model health

Install the current core and optional knowledge dependencies. Back up the target
database and apply Alembic in a maintenance window. The head is
`0008_model_health_lookup`. It adds the composite model, source, assessment
time, and prediction ID index. FleetMind exercised this migration on disposable
PostgreSQL. Applying it to an existing instance is an explicit operator action.
On a large history table, plan for index creation time and its write lock.

Model Health is on the Model Intelligence page for authenticated viewers,
engineers, and administrators. The existing dashboard, Copilot, and broker
worker can run with Prometheus, Grafana, and MLflow disabled.

## Model reference and screening

`python -m scripts.generate_model_reference` verifies the AI4I CSV SHA-256
against frozen metadata, reconstructs the original stratified split with seed 42,
and uses all 8,000 training records. It uses the fitted model for scores and
uses the original alert thresholds. The 2,000 held-out rows are excluded.
The JSON artifact records the schema version, dataset hash, split, sample size,
both frozen artifact hashes, and a canonical reference fingerprint. The API
verifies the fingerprint and artifact hashes at startup. Store the artifact and
report with the trusted release bundle. The digest is an integrity check.

The selected source is queried separately for 24 hours, 7 days, or 30 days.
Windows use assessment creation time. Comparisons use the most recent 5,000
matching assessments and report when the limit was reached. Declared telemetry,
simulated, manual, and unknown provenance remain distinct. Source declarations
do not independently identify a physical measurement.

- Continuous fields use internal training deciles, with duplicate edges and
  extrema removed. The first and last bins include out-of-range values. PSI
  compares the proportions of scores and sensor values against those bins.
- Machine type and alert tier use fixed categories with Jensen–Shannon
  divergence in bits. Both statistics add a Jeffreys pseudocount of 0.5 per bin
  before normalization.
- Screening requires 100 operational assessments from the selected source.
  PSI uses descriptive review and elevated thresholds of 0.10 and 0.25.
  Categorical divergence uses 0.05 and 0.10 bits. These are screening
  heuristics. Synthetic reference data and sparse categories can affect the
  values. A threshold crossing warrants examining provenance, sampling, and
  operating context with a qualified reviewer.
- The view shows distribution shares and available counts at smaller sample
  sizes. Scores remain uncalibrated. Alerts retain the frozen thresholds.

## Private metrics and dashboards

Run `python -m scripts.prepare_observability --worker-port 9101` from a
private working directory. It generates a random scraper credential and
Grafana password in `.env.observability`, which Git ignores. Restrict OS
permissions on this directory. Docker's service users require read access
to their own mounted secret files. Set this variable before starting the API
and workers:

    $env:FLEETMIND_METRICS_TOKEN_FILE = (Resolve-Path .env.observability/scrape.token).Path

Start the API on the usual local port. For a telemetry worker add
`--metrics-port 9101` to its existing command. Each additional worker uses a
different metrics port. Add that port to the worker target JSON. Start the
optional profile with:

    docker compose -f compose.observability.yaml --profile observability up -d --wait

Open Grafana on `http://127.0.0.1:3100` as `fleetmind-observer`. Retrieve the
generated password only from the private file. Provisioning imports six
dashboards and the Prometheus data source. Grafana has loopback publication.
Prometheus stays on the Compose network. API and worker scrapes require the
dedicated bearer token. The Next.js bridge has no metrics forwarding route.
Default discovery uses Docker Desktop's `host.docker.internal`. On a native
Linux host, configure private target connectivity explicitly. Keep scrape
ports and the broker within trusted network boundaries.

The profile limits each container to 512 MiB and 0.75 CPU. The Prometheus
volume retains up to seven days or 512 MB of time-series data. Grafana persists
configuration and account state separately. Workers initialize their own
model, main database pool, and reporter pool. Test total PostgreSQL connection
and memory use when adding replicas.

| Metric family | Meaning |
| --- | --- |
| `fleetmind_http_requests_total` and `fleetmind_http_request_duration_seconds` | Finished request lifecycles and elapsed ASGI wall time by fixed method, route template, and status. Pre-routing rejections use `unmatched`. Disconnects before a response use `no_response`. SSE HTTP durations include stream lifetime. |
| `fleetmind_operation_duration_seconds` | Timed preparation, model inference, persistence, telemetry transaction, serialization, pool checkout, poll, offset acknowledgement, retrieval, embedding, and provider operations. Phases can overlap. |
| `fleetmind_telemetry_events_total` and `fleetmind_telemetry_rejected_total` | Received, processed, duplicate, invalid, retry, DLQ, and committed milestones. A committed offset may acknowledge a duplicate or a rejected event. |
| `fleetmind_worker_committed_lag` and `fleetmind_worker_running` | Latest assigned-partition committed lag and worker lifecycle. Unavailable lag is emitted as NaN. Prometheus `up` distinguishes an unreachable process. |
| `fleetmind_dependency_available` | API PostgreSQL probe and worker PostgreSQL/reporting and Redpanda metadata outcomes. No recorded check means no series. |
| `fleetmind_sse_connections` and `fleetmind_sse_closed_total` | Open responses and responses closed normally or interrupted. Transport closure is separate from application response status. |
| `fleetmind_copilot_responses_total`, `fleetmind_copilot_provider_failures_total`, `fleetmind_copilot_tool_duration_seconds`, `fleetmind_copilot_reported_tokens_total` | Actual orchestration results, provider attempt errors, validated-tool durations, and reported token counts. Missing provider usage is left unreported. |
| `fleetmind_process_cpu_seconds_total` and `fleetmind_process_resident_memory_bytes` | Lifetime CPU time and current process RSS. Rates are calculated per process. |

Configure one Uvicorn process per scrape target and one listener per independent
worker. To scale the API, register distinct replica ports and place a trusted
gateway in front of them. Multiple processes sharing one Uvicorn port would
make consecutive scrapes hit different counters. Dashboards aggregate per-target
rates after Prometheus handles counter resets. FleetMind rate and concurrency
limits are per API process. A multi-replica deployment also requires
gateway-level limits. Grafana and Prometheus access are separate operator
accounts and must stay private.

## Logs and optional tracing

Structured events carry UTC time, an operation, an outcome or error category,
wall duration where measured, and a correlation ID. The Next.js bridge
accepts a lowercase 32-hex request ID or generates one, then passes it through
to FastAPI. Validated telemetry uses the existing event UUID as its correlation
ID. These IDs are excluded from metric labels. Logs exclude passwords, raw
tokens, provider keys, private reasoning, conversation text, and raw telemetry
bodies. Keep query strings out of access logs and configure retention at ingress.

Install `requirements-mlops.txt` to enable optional HTTP OTLP export. Configure
`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` for a trusted collector. The
`FLEETMIND_TRACE_SAMPLE_RATE` default is 0.02 and the cap is 0.25. Batch
queues hold at most 128 spans and use a three-second export timeout. Span
names are fixed and payloads and identifiers are omitted. Sampling is local
to each process. The application starts without a collector and remains
functional with tracing disabled.

## Experiment lineage

The optional dependencies enable local SQLite-backed MLflow records. The
tracking directory contains the database and artifacts. Keep it private and
outside version control. These commands create local runs without opening a
tracking server:

    python -m scripts.run_xgboost_baseline --tracking-directory .env.experiments
    python -m scripts.import_model_lineage --tracking-directory .env.experiments

The first command records a new validation-only experiment, with dataset hash,
split seed, features, estimator parameters, measured metrics, runtime versions,
and artifact hashes. Its model is an experimental artifact. The second imports
the documented frozen metadata and held-out report and marks the run
`retrospective_import`. The run’s creation time is its import time. FleetMind
retains manual review for any model promotion.

## Retrieval regression and live-provider evaluation

The default MiniLM model, checkpoint revision, and 384-dimensional vectors
were unchanged on 50 tested inputs. The maximum absolute difference was 0.
The original 32-query regression was run against an index generated by the
older libraries. The new development and previously unused test suites were
fixed before scoring. Metrics below use the 5 highest-ranked chunks and count
each relevant document once.

| Query set | Mode | Recall@5 | MRR | nDCG@5 |
| --- | --- | ---: | ---: | ---: |
| 32 regression queries, before and after | Semantic | 0.9881 | 0.9286 | 0.9339 |
| 32 regression queries, before and after | Keyword | 0.1429 | 0.1429 | 0.1429 |
| 32 regression queries, before and after | Hybrid | 0.9881 | 0.9464 | 0.9471 |
| 12 development queries | Semantic and hybrid | 0.9500 | 0.9250 | 0.8883 |
| 16 test queries | Semantic and hybrid | 1.0000 | 0.8654 | 0.8940 |
| Development and test | Strict keyword | 0.0000 | 0.0000 | 0.0000 |

Strict phrase and term matching missed all answerable passages in the new
natural-language sets. Semantic and hybrid returned candidates for every
out-of-domain question. Ranking is not an answerability judgment. The
checked-in reports include the misses, query timings, and dataset hashes.
Hybrid regression p95 was 57.4 ms before and 48.6 ms after. Cold encoder
warmup was 18.8 s before and 25.3 s after. Both latency measurements are
single-run observations under the validation workload.

To regenerate metrics on a disposable, migrated, seeded database run
`python -m scripts.evaluate_knowledge --suite regression` and repeat for
`development` and `test`. Compare encoder compatibility using
`scripts.compare_embeddings` with a baseline snapshot. If an encoder update
moves vectors beyond the documented tolerances, set
`FLEETMIND_EMBEDDING_PROFILE` to a new label. Seed the same corpus from its
original source files on an isolated copy, preserving the chunk size and
overlap. New vectors have a separate model key. Validate coverage and
retrieval before switching the serving profile. Keep the previous index until
the new one is reviewed. Reindexing remains an explicit action.

The original 51 deterministic cases remain available through
`scripts.evaluate_copilot`. The new
`scripts.evaluate_copilot_live --output reports/live-local.json` validates a
10-case harness backed by synthetic fixtures, exercises authorization against
the actual middleware, and checks provider errors with a local mock transport.
It reports live behavior as pending until a real provider is requested.
With an authorized local provider, add `--live`. Hosted calls also require
explicit `--allow-paid` authorization. The report records actual latency and
provider usage. Use `--pricing-usd-per-million INPUT OUTPUT` only with a
verified price schedule. Real-provider results and deterministic checks are
reported separately.

## Scaling and database behavior

The reproducible worker command is:

    python -m scripts.benchmark_worker_scaling --disposable --bootstrap 127.0.0.1:19097 --rate 60 --seconds 15 --burst 300 --output reports/worker-local.json

Set `FLEETMIND_TELEMETRY_TEST_DATABASE_URL` to a migrated disposable database
whose name starts with `fleetmind_` and ends in `_test`. The paired runs
used six partitions, 24 registered fixture assets, one database connection
per worker plus one reporter connection, and one OpenMP thread per worker.
Durability checks verified all 2,400 predictions. Sampled peak lag is the
largest single worker sample. Every run drained to zero committed group lag.

| Workload | Workers | Commits/s | Seconds to final commit | Observation-to-commit p50 / p95 / p99 | Max sampled worker lag |
| --- | ---: | ---: | ---: | --- | ---: |
| 900 events at target 60/s | 1 | 17.0 | 52.94 | 20.07 / 35.56 / 36.37 s | 703 |
| 900 events at target 60/s | 2 | 41.6 | 21.64 | 3.58 / 6.38 / 6.58 s | 139 |
| 300-event burst | 1 | 19.0 | 15.77 | 6.06 / 12.50 / 12.96 s | 252 |
| 300-event burst | 2 | 37.7 | 7.97 | 2.33 / 4.66 / 4.85 s | 95 |

The single-worker sustained run averaged 34.80 ms of database work excluding
inference, 12.98 ms of model inference, 7.50 ms acknowledging the offset,
3.65 ms checking out the connection, and 1.09 ms preparing features.
Connection checkout is included in database time. Kafka poll time includes idle
waits. The report includes all phases, CPU samples, and peak RSS. Total peak
RSS was roughly 198 MiB for one worker and 395 MiB summed across two.
Background validation ran on the same host. Compare these local results with
that variability in mind. The original Milestone 10A run had different
conditions.

Sequential per-event transactions and synchronous acknowledgement remain in
place. Pool sizes greater than one do not give a single sequential worker
parallel database work. Additional workers share the group across partitions.
The serialized commit cursor, durable deduplication, and committed-only SSE
remain in use. Batch transactions or deferred offset acknowledgement would
change recovery behavior and require a separate reliability evaluation.

## Desktop and mobile browser results

Edge used two clean disposable databases, the production frontend builds,
a 1,440 px viewport, 60 preloaded assessments, and 240 more at a target of
50 events/s. The test waited for the last durable cursor and checked keyboard
closure of the investigation drawer.

| Measurement | Before | After |
| --- | ---: | ---: |
| Telemetry long tasks | 8 (58–108 ms) | 1 (80 ms) |
| Renderer task time in the telemetry window | 1,975 ms | 706 ms |
| Telemetry measurement window | 18.62 s | 15.40 s |
| Renderer task time during dashboard refresh | 334 ms | 288 ms |
| Dashboard refresh long tasks | 0 | 0 |
| JavaScript heap sample after the stream | 9.92 MiB | 17.07 MiB |

The candidate memoizes individual feed rows, schedules feed updates as
transitions, renders chart updates at lower priority, and polls telemetry
diagnostics once per 10-second reporting bucket. Dashboard refresh and
reconnect behavior continue to use the existing transport. The desktop
measurements are single paired runs on an 8-logical-core, 15.8 GiB Windows
host. The stream window includes producer startup and delivery time.
At 320 px Edge reached the final committed cursor, rendered Model Health's
insufficient and ready states, and passed the investigation keyboard check.
The mobile candidate recorded two long tasks of 129 and 101 ms. The two
long tasks reported in Milestone 10B used a different workload.

## Dependency remediation

The Milestone 11A audit's 19 entries represent 12 unique advisories. FleetMind
upgraded Sentence Transformers 5.2.0 to 5.6.0, Transformers 4.57.6 to 5.17.0,
and setuptools 65.5.0 to 84.1.0. The tested packages preserve MiniLM results
on the previous index, SHAP availability, and frozen prediction outputs.
The Python package audit reported zero findings in its matched candidate
packages, including the optional MLflow and OTLP packages. npm audit also
reported zero. The editable FleetMind package and the +cpu PyTorch
distribution have no direct PyPI audit match. The audit report records
those omissions.

| Package | Advisory | Published severity | Fixed versions recorded by the baseline scanner |
| --- | --- | --- | --- |
| sentence-transformers | [PYSEC-2026-4164](https://github.com/advisories/GHSA-jhr6-gm9c-rqjv) | Critical | 5.6.0 |
| setuptools | [PYSEC-2022-43012](https://github.com/advisories/GHSA-r9hx-vwmv-q579) | High | 65.5.1 |
| setuptools | [PYSEC-2025-49](https://github.com/advisories/GHSA-5rjg-fvgr-3xxf) | High | 78.1.1 |
| setuptools | [PYSEC-2026-1918](https://github.com/advisories/GHSA-cx63-2mw6-8hw5) | High | 70.0.0 |
| setuptools | [PYSEC-2026-3447](https://github.com/advisories/GHSA-h35f-9h28-mq5c) | Moderate | 83.0.0 |
| setuptools | [GHSA-xmj3-9gf7-h52w](https://github.com/advisories/GHSA-xmj3-9gf7-h52w) | Low | 84.1.0 |
| transformers | [PYSEC-2025-217](https://github.com/advisories/GHSA-8jfx-5878-hv4v) | High | No explicit fixed version in the baseline report |
| transformers | [PYSEC-2026-2288](https://github.com/advisories/GHSA-69w3-r845-3855) | Moderate | 5.0.0rc3, 5.0.0 |
| transformers | [PYSEC-2026-2289](https://github.com/advisories/GHSA-29pf-2h5f-8g72) | High | 5.3.0 |
| transformers | [PYSEC-2026-2290](https://github.com/advisories/GHSA-fgcw-684q-jj6r) | High | 5.5.0 |
| transformers | [PYSEC-2026-3929](https://github.com/advisories/GHSA-xrqw-3rrv-vx5w) | High | 5.10.0 |
| transformers | [PYSEC-2026-4174](https://github.com/advisories/GHSA-x9r9-c232-4q39) | High | No explicit fixed version in the baseline report |

The Sentence Transformers issue concerns custom Python in model directories.
FleetMind's default embedding load uses a pinned MiniLM checkpoint, CPU
safetensors, offline mode, and disabled remote code. Keep deployment
directories and caches trusted. FleetMind does not expose model loading or
checkpoint conversion as an API. The Transformers findings involve paths
such as training checkpoint reloads, alternative model configurations,
generation code, or export. The shipped MiniLM path uses none of those
workflows. The setuptools findings mainly affect build tooling and dependency
installation. Use trusted wheels and protect deployment caches.

The separate PyPI screening of PyTorch 2.9.1, the upstream version of the
installed 2.9.1+cpu wheel, returned five advisory entries representing four
CVEs. This screens the base release rather than validating the exact wheel.
Review the reported version ranges and availability of patched CPU wheels
before upgrading. The model-loading boundary still requires vetted
safetensors. FleetMind's MiniLM inference workflow does not use PT2 archive
loading, TorchScript compilation, LSTM cells, or PyTorch checkpoint loading.
Container images and the host OS need their own vulnerability review.

| PyTorch base-release findings | Published or scanner-reported fix |
| --- | --- |
| [PYSEC-2026-139 and CVE-2026-4538](https://nvd.nist.gov/vuln/detail/CVE-2026-4538) | No fix version reported by the scanner |
| [PYSEC-2025-194 and CVE-2025-3000](https://github.com/advisories/GHSA-rrmf-rvhw-rf47) | 2.13.0 in the observed scan |
| [PYSEC-2025-195 and CVE-2025-3001](https://github.com/advisories/GHSA-qfhq-4f3w-5fph) | 2.10.0 in the observed scan |
| [PYSEC-2026-2286, PYSEC-2026-1856, and CVE-2026-24747](https://github.com/advisories/GHSA-63cw-57p8-fm3p) | 2.10.0 |

## Validation results

The final run passed 94 Python tests with disposable PostgreSQL and Redpanda,
four Next.js proxy tests, and all 51 scripted Copilot cases. Ruff, Alembic
schema checks, ESLint, standalone TypeScript, and the production Next.js build
passed. The two frozen XGBoost hashes matched before and after validation.

The optional Compose profile provisioned Grafana's protected account, six
dashboards, and its private Prometheus data source on Windows Docker Desktop.
Both scrape targets were up, and Prometheus accepted all 26 dashboard
queries. Grafana's API dashboard rendered in Edge at 1,440 and 320 px.
The authenticated app status, dashboard, telemetry storage status, and
Model Health routes responded with Redpanda stopped.

A loopback OTLP collector received 41 sampled spans from 160 attempts at a
25% sampling rate. Each span contained only the fixed validation operation
name and no application attributes. Local SQLite MLflow recorded an
experimental validation run and a separate retrospective lineage import.
The live-provider harness passed its authorization and transport fixtures.
Real-provider quality and estimated costs await an authorized provider run.

To reproduce the browser comparison, build the pre-change and current
frontends and run `node scripts/benchmark_monitoring_browser.mjs VARIANT FRONTEND_DIR REPORT_PATH 1440`
against a fresh disposable browser database for each variant. Use Node.js with
built-in WebSocket support and Microsoft Edge. Set `DATABASE_URL` to a fresh
`fleetmind_m11b_browser_*_test` database and set
`FLEETMIND_TELEMETRY_TEST_BOOTSTRAP` to the disposable broker.

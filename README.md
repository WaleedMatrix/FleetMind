# FleetMind

### Predictive Maintenance AI System

FleetMind is a machine learning application designed to
estimate equipment failure risk using operational sensor
measurements.

## Project Status

Development in progress.

## Objectives

- Exploratory data analysis
- Predictive maintenance classification
- Model evaluation and threshold optimization
- Explainable machine learning
- REST API development
- Interactive monitoring dashboard

## Dataset

UCI AI4I 2020 Predictive Maintenance Dataset.

The dataset is synthetic and is used strictly as an
educational machine learning benchmark.

## Technology Stack

- Python
- Pandas and NumPy
- Scikit-learn
- XGBoost
- FastAPI
- React / Next.js
- Docker

## Disclaimer

FleetMind is a demonstration project.
It is not intended for operational maintenance decisions.

## Sign in and manage access

Milestone 11A requires a FleetMind account for the dashboard and API. Viewers
can monitor assessments. Engineers can submit readings, manage assets, and
use private Copilot conversations. Administrators can also manage users and
review audit events.

1. Install the current `requirements.txt` and confirm `DATABASE_URL` points
   to the intended instance. Back up an existing database before proceeding.
2. Run `python -m alembic upgrade head`, then confirm
   `python -m alembic current` reports `0007_application_security`.
3. Run `python -m scripts.manage_security bootstrap --username your-admin`.
   The CLI prompts for a password and confirmation without echoing either.
4. For local development, set `FLEETMIND_AUTH_INSECURE_LOCAL_HTTP=1` and exact
   loopback frontend origins as shown in `.env.example`. Start FastAPI with
   `python -m uvicorn fleetmind.api.main:app --host 127.0.0.1 --port 8000`.
   From `frontend`, run `npm run dev -- --hostname 127.0.0.1` and open
   `http://127.0.0.1:3000/login`.

`GET /health` is a public liveness probe. Use authenticated
`GET /api/v1/system/status` for model readiness. Conversation owners are
assigned at creation. Administrators can explicitly archive or adopt legacy
conversations from **Administration → Legacy conversations**.

See [FleetMind security architecture](docs/security.md) for the permission
matrix, simulator credentials, deployment settings, and audit findings.

## Asset Intelligence

Open **Assets** from the dashboard to register equipment and see its recorded
assessments, source labels, score trend, and recent alerts. The inference lab can
assign a manual or simulated reading to a registered asset. The asset ID and
machine type are fixed at registration so saved readings stay attributable.

Predictions without an asset ID remain unassigned. Historical readings without
provenance remain unknown. The sensor simulator labels new readings as simulated.
API clients can declare telemetry, and FleetMind displays that declaration
without independently verifying its origin. Model scores are uncalibrated.

### Database migration

1. Install the Python dependencies with `python -m pip install -r requirements.txt`.
2. Set `DATABASE_URL` for the target PostgreSQL database. For local Docker
   development, use the port and credentials in `.env.example` and start
   PostgreSQL with `docker compose up -d db`. Back up an existing database
   before upgrading it.
3. From the repository root, run `python -m alembic upgrade head` before
   deploying the updated API. Run `python -m alembic current` to confirm the
   revision is at the current Alembic head.

The online migration recognizes the pre-Alembic prediction table and retains
its rows and ID sequence. It can also initialize an empty PostgreSQL database.
The migration is forward-only. Previously saved predictions retain their sensor
values, scores, timestamps, and IDs.

Set `FLEETMIND_MIGRATION_TEST_DATABASE_URL` to a disposable development
PostgreSQL database to run the fresh-install and legacy-upgrade tests with
`python -m pytest tests/integration/test_migrations.py`.

### Asset API

| Endpoint | Purpose |
| --- | --- |
| `POST /api/v1/assets` | Register an asset. |
| `GET /api/v1/assets` | Search by ID, name, or location with `q`, filter by `machine_type`, and paginate with `limit` and `offset`. |
| `GET /api/v1/assets/{asset_id}` | Read the asset record. |
| `PATCH /api/v1/assets/{asset_id}` | Update display name, location, or description. |
| `GET /api/v1/assets/{asset_id}/predictions` | List readings with `limit`, `offset`, `source`, `alert_level`, and `alerts_only` filters. |
| `GET /api/v1/assets/{asset_id}/summary` | Get stored assessment counts, mean score, and latest timestamp. |

The existing prediction endpoint accepts optional `asset_id` and `source`
fields. Supported sources are `unknown`, `manual`, `simulated`, and `telemetry`.

## Model Intelligence

Use **Explain assessment** in a saved prediction’s drawer to view signed
Tree SHAP attributions and their cumulative waterfall. The server uses the
original reading, fitted preprocessing, and matching model version. It checks
that the saved score is reproducible and that the baseline plus contributions
matches the classifier’s raw margin. The margin and contributions are measured
in log-odds. The logistic transform produces the uncalibrated score.

`GET /api/v1/predictions/{prediction_id}/explanation` computes an explanation on
demand. A missing prediction returns 404, a different saved model version
returns 409, and unavailable or unverifiable explanations return 503.
`GET /api/v1/model/intelligence` serves the model metadata, training-sample
importance, and the existing version-matched held-out evaluation.

To reproduce [the global SHAP report](reports/global_shap_xgboost_v1.json), install
the updated requirements and run `python scripts/generate_global_shap.py` from
the project root with the frozen artifact and original AI4I CSV available.
The generator verifies the CSV digest, uses the existing stratified split,
samples 512 training rows with seed 42, and applies path-dependent TreeExplainer.
For machine type, it sums the one-hot contributions per row before taking the
mean absolute value. The thermal gap stays separate because it is a fitted
feature derived from process minus air temperature. The generator reads no
held-out features for explanation and performs no fitting or tuning.

The existing held-out report describes synthetic AI4I observations with a rare
failure class. Scores have no probability calibration or validated
time-to-failure interpretation. SHAP describes the fitted model’s behavior
under its attribution assumptions. It cannot confirm physical causes, and
maintenance decisions require human confirmation.

## Maintenance Knowledge Base

Milestone 9A adds retrieval and source citations. Search results are untrusted
document text. They provide review context and carry no authority to direct
maintenance, execute instructions, or authorize work.

### PostgreSQL upgrade

1. Back up the database and confirm that Compose is using the existing
   `fleetmind_pgdata` volume under the same project name.
2. Run `docker compose pull db` and `docker compose up -d db`. The service now
   uses `pgvector/pgvector:0.8.2-pg17` with the same PostgreSQL major version,
   data directory, and volume mapping.
3. Install the updated base requirements. Set `DATABASE_URL` for the intended
   database and run `python -m alembic upgrade head`. Confirm
   `0003_maintenance_knowledge` with `python -m alembic current` and run
   `python -m alembic check`.

The additive, forward-only migration creates four knowledge tables and enables
the `vector` extension in `public`. The database role needs extension creation
privileges, or an administrator must enable pgvector first. Keep `public` on the
connection’s search path. The migration preserves prediction and asset tables.

### CPU embeddings and ingestion

For the tested Windows and Python 3.11 environment, activate the project
environment and install the CPU wheel and optional retrieval dependencies.

```powershell
python -m pip install -r requirements.txt
python -m pip install 'torch==2.9.1+cpu' --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements-knowledge.txt
$env:OMP_NUM_THREADS = '4'
$env:FLEETMIND_EMBEDDING_OFFLINE = '0'
python scripts/knowledge.py prefetch
$env:FLEETMIND_EMBEDDING_OFFLINE = '1'
python scripts/knowledge.py seed
```

The encoder defaults to offline mode and loads on first use. The default
MiniLM revision is pinned and produces 384-dimensional embeddings. For a
different remote model, set `FLEETMIND_EMBEDDING_MODEL` and its full commit SHA
in `FLEETMIND_EMBEDDING_REVISION`. An administrator can instead supply a local
Sentence Transformers directory with safetensors weights through
`FLEETMIND_EMBEDDING_DIRECTORY`. A local model uses a file fingerprint when no
explicit revision is set. Treat an explicit revision as immutable. After
switching models, ingest the source files again to populate the new profile.
Queries compare vectors belonging to the active model, revision, and dimensions.

Use UTF-8 Markdown with `#` headings or plain text. The default 100-word chunks
share 15 words within a section. Adjust `--chunk-size` and `--overlap` as needed.
The encoder rejects text that exceeds the model token limit. Keep its batch
size modest on CPU. Each API worker can hold its own encoder in memory.

```powershell
python scripts/knowledge.py ingest notes.txt --id field-notes --title "Field notes" --category maintenance --source-kind reference
python scripts/knowledge.py list
python scripts/knowledge.py inspect field-notes
python scripts/knowledge.py events field-notes
python scripts/knowledge.py remove field-notes
```

Re-ingest with the same ID to update a document. Unchanged chunks keep their
citations and vectors. Matching embedding inputs are reused within the same
model profile. Duplicate normalized documents with different IDs are rejected.
Remove deletes that document’s chunks and vectors while retaining the ingestion
event. Source references are logical identifiers. Ingestion is a local CLI
operation and search is read-only.

### Retrieval and evaluation

The read-only API exposes `GET /api/v1/knowledge/status`,
`GET /api/v1/knowledge/documents`, `GET /api/v1/knowledge/documents/{document_id}`,
and `POST /api/v1/knowledge/search`. Search accepts `query`, `top_k` (1–20),
`mode` (`semantic`, `keyword`, or `hybrid`), and optional filters for document
IDs, category, source kind, or source reference.

Semantic search uses exact pgvector cosine ranking. Keyword search uses
English `websearch_to_tsquery` and a GIN-indexed text vector. Hybrid search
combines ranked candidates with reciprocal rank fusion using a constant of
60. Diagnostics report mode, candidate counts, phase timings, and fallback.
Hybrid can fall back to keyword search when the configured embeddings are
unavailable. Cosine similarity, text rank, and RRF are ranking signals, with no
probability calibration. Exact vector search is intended for the small corpus
and should be benchmarked at larger sizes.

The [starter corpus](docs/knowledge/manifest.json) is FleetMind project
documentation, summaries of existing model metadata, and labeled general
review guidance. Use approved site and manufacturer materials for
equipment-specific procedures. Human review is required to confirm faults.

Run the frozen [32-query evaluation](docs/knowledge/retrieval-evaluation.json)
with the seeded corpus in a development database.

```powershell
python scripts/evaluate_knowledge.py --top-k 5 --output reports/knowledge_retrieval_local.json
```

Recall, MRR, and nDCG use document relevance at the returned chunk ranks.
Repeated chunks from a document consume rank positions and earn relevance
credit only once. Queries without a relevant document are assessed separately
by counting whether retrieval returned any results. The
[measured report](reports/knowledge_retrieval_m9a.json) includes misses, top
documents for each query, corpus hashes, dependency versions, and warm latency.
Semantic results can include irrelevant passages for out-of-domain queries.

#### Measured reference run

The Windows CPU run used PostgreSQL 17.10, pgvector 0.8.2, four OpenMP threads,
and 18 chunks from eight starter documents. Metrics cover 28 answerable
questions. Latencies cover all 32 warm service-layer queries per mode and
include the database and, where applicable, query embedding.

| Mode | Recall@5 | MRR@5 | nDCG@5 | Query p50 / p95 |
| --- | ---: | ---: | ---: | ---: |
| Semantic | 0.988 | 0.929 | 0.934 | 49.9 / 245.8 ms |
| Keyword | 0.143 | 0.143 | 0.143 | 9.4 / 14.3 ms |
| Hybrid | 0.988 | 0.946 | 0.947 | 51.0 / 60.4 ms |

Semantic and hybrid each missed the provenance document for the ambiguous
simulated-alert query `b04` while finding its other relevant documents.
Both returned passages for all four out-of-domain questions. Keyword search
returned no passages for those four queries and missed 24 answerable queries.
The small corpus and single run limit generalization of relevance and tail
latency measurements.

The starter index took 22.10 seconds from a cold process with cached model
files, including commit and 1.26 seconds of embedding computation. A second
process reused all 18 vectors and spent 18.23 seconds verifying the index,
including encoder initialization. The encoder warmup for evaluation took
18.58 seconds. In a separate FastAPI smoke test, the Windows process working
set rose from about 267 MiB to 560 MiB after its first hybrid request. This
includes the existing prediction and SHAP runtime. Worker count and batch
size affect aggregate memory use.

Set `FLEETMIND_MIGRATION_TEST_DATABASE_URL` to a disposable PostgreSQL 17 database
with pgvector available to include the PostgreSQL tests in `python -m pytest`.

## Copilot backend

Milestone 9B adds `POST /api/v1/copilot/chat` and
`GET /api/v1/copilot/status`. Copilot starts disabled. Status reports
configuration, and the provider connection is checked when a chat request
needs it. The existing prediction and monitoring API can run independently.
Copilot requires an engineer or administrator session. Set provider credentials
on the API server.

### Providers and budgets

The server reads these variables from its environment or local `.env`.

| Variable suffix after `FLEETMIND_COPILOT_` | Default / meaning |
| --- | --- |
| `PROVIDER` | `disabled`, `openai`, `ollama`, `local_evidence`, or `mock` |
| `MODEL` | Model name from your provider. The model must support tools and JSON output. |
| `BASE_URL` | OpenAI uses `https://api.openai.com/v1`. Ollama uses `http://127.0.0.1:11434/v1`. Custom endpoints require HTTPS or loopback HTTP. |
| `API_KEY` | Server-side credential for the chosen hosted provider. For the default OpenAI host, `OPENAI_API_KEY` also works. |
| `TOKEN_PARAMETER` | `max_completion_tokens` for OpenAI or `max_tokens` for Ollama. Override for compatible servers if needed. |
| `REQUEST_TIMEOUT`, `PROVIDER_TIMEOUT`, `TOOL_TIMEOUT` | 45, 12, and 24 seconds, respectively |
| `MAX_ROUNDS`, `MAX_TOOLS` | 4 tool rounds and 8 attempted calls per request, including selected-asset verification |
| `MAX_TOKENS`, `RETRIES` | 600 requested output tokens per completion and one retry for transient failures |

Hosted use requires provider API credentials and billing or available API
credits. API billing is separate from ChatGPT subscriptions. With Ollama, run
a local model that supports tool calls through its OpenAI-compatible endpoint.
Hosted requests send the question, submitted context, and tool evidence to the
configured provider.
The default `mock` configuration abstains. The evaluation harness supplies
scripted calls for deterministic testing.

Set `FLEETMIND_COPILOT_PROVIDER=local_evidence` in the server's `.env` and
restart FastAPI to use Copilot without a generative model or API key. The
workspace labels this mode **Local evidence search**. It selects and cites
matching saved facts from the knowledge base, scoped records, or model report.
It supports targeted questions such as “How is the thermal gap calculated?”
and may abstain on broader questions. Seed the knowledge corpus before using it.

```powershell
$env:FLEETMIND_COPILOT_PROVIDER = 'openai'
$env:FLEETMIND_COPILOT_MODEL = 'your-tool-capable-model'
# Set FLEETMIND_COPILOT_API_KEY in the server environment
python -m uvicorn fleetmind.api.main:app --host 127.0.0.1 --port 8000
```

Seed the knowledge corpus from the previous section before asking knowledge
questions. To test the API, send a question and optionally a registered
`asset_id` and up to four recent context messages.

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/copilot/status
$body = @{ question = 'How is the thermal gap calculated?' } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/api/v1/copilot/chat -Method Post -ContentType 'application/json' -Body $body
```

Responses include a status, answer, cited facts, record references, limitations,
and diagnostics. Clarification and insufficient evidence use HTTP 200, invalid
input uses 422, and provider unavailability uses 503 or 504 for deadlines.
Token counts reflect usage supplied by successful provider responses.

### Evidence controls

The planner can call a fixed, read-only registry over FleetMind services.
Arguments are strictly validated. PostgreSQL tool transactions are read-only
and use a statement timeout. Four workers bound in-process tool concurrency.
A timed-out embedding or SHAP calculation already running on a worker can
finish in the background before that worker becomes available again.

Candidate retrieval uses a bounded lexical OR query built from PostgreSQL
lexemes, up to three query aspects, document diversity, and a conservative
term-overlap and specific-identifier check. The 9A search endpoint retains
its original behavior. Candidate checks use no cosine or RRF confidence cutoff.

The provider selects fact IDs from evidence collected during the request.
The server assembles the answer from canonical record facts and attributed
document quotations. Invented facts, arbitrary prose, and unknown IDs are
discarded. A citation establishes where the exact statement came from.
Whether the material fully answers a question and whether a document is
factually reliable still need review. User context and retrieved passages
are untrusted, and suspicious instruction-like passages are excluded.
Maintenance decisions require human confirmation. The original chat endpoint
returns a single structured response and does not write conversation history.

### Evaluation

```powershell
python -m scripts.evaluate_copilot --output reports/copilot_mock_local.json
python -m scripts.evaluate_copilot_retrieval --output reports/copilot_retrieval_local.json
python -m scripts.evaluate_copilot --live-api http://127.0.0.1:8000 --username your-engineer --output reports/copilot_live_local.json
```

The [51 scripted cases](docs/copilot/evaluation.json) cover record lookup,
prediction investigation, SHAP, multiple tools, maintenance knowledge,
ambiguity, unanswerable queries, injection, malformed arguments and citations,
timeouts, and budget limits. The scripted run measures expected control paths,
status and answer checks, citation integrity, and latency. It measures no live
model quality. The opt-in live subset covers questions answerable from the seeded
knowledge base or model report and records required-tool coverage, argument
validity, expected facts, abstention, latency, and provider-reported tokens.
For a live quality review, inspect each selected fact in context against the
cited source and check whether the answer addresses every part of the question.

The [9B retrieval report](reports/copilot_retrieval_m9b.json) compares the
original corpus and 32 held-out 9A questions against the new candidate path.
The admission rules were set using separate development checks in the unit
tests. The original 9A report is retained. On this run, the hybrid path
recovered provenance for the simulated-alert question and returned no
passages for the four out-of-domain questions. Conservative admission missed
three answerable paraphrases (`s05`, `a01`, and `b03`) and reduced overall hybrid
recall. Expanded keyword retrieval improved substantially within this corpus.

| Mode | Recall@5 before / after | MRR@5 before / after | nDCG@5 before / after |
| --- | ---: | ---: | ---: |
| Semantic | 0.988 / 0.875 | 0.929 / 0.857 | 0.934 / 0.853 |
| Keyword | 0.143 / 0.875 | 0.143 / 0.839 | 0.143 / 0.839 |
| Hybrid | 0.988 / 0.875 | 0.946 / 0.857 | 0.947 / 0.853 |

The new hybrid candidate path took 62.5 ms median and 192.7 ms p95 after
MiniLM warmup. The [scripted report](reports/copilot_mock_m9b.json) passed all
51 cases, with 25.8 ms median and 46.8 ms p95 request latency in the fixture
process. An API smoke test with real MiniLM and disposable PostgreSQL resolved
the thermal-gap citation in 18.39 seconds on a cold encoder, with a mocked
provider transport. Live OpenAI-compatible and Ollama quality, latency, and
token usage remain unverified.

## Maintenance Copilot workspace

Open `/copilot` from the dashboard, Alert Intelligence Center, an asset page,
a prediction drawer, or Model Intelligence. Asset and prediction links carry
the saved record IDs. Starting an investigation creates a conversation, and
the URL can reopen that conversation. Use the history panel to search titles
and saved messages or switch between active and archived conversations.

### Apply the additive migration

With the existing PostgreSQL 17 and pgvector development service running,
confirm that `DATABASE_URL` points at the intended database, then run:

```powershell
python -m alembic current
python -m alembic upgrade head
python -m alembic check
```

Revision `0004_copilot_conversations` adds `copilot_conversations` and
`copilot_messages`. It preserves existing assets, prediction history, and the
knowledge index. Downgrading across this revision is disabled because it would
discard saved conversations. Migration and concurrency tests use a disposable
PostgreSQL database supplied as `FLEETMIND_MIGRATION_TEST_DATABASE_URL`.

### Conversation API

The following examples use a shell configured as in the provider section above.
Use a registered asset ID or an existing, compatible prediction ID in the optional
`asset_id` and `prediction_id` fields when creating or updating a conversation.

```powershell
$copilot = 'http://127.0.0.1:8000/api/v1/copilot/conversations'
$thread = Invoke-RestMethod $copilot -Method Post -ContentType 'application/json' -Body '{"title":"Alert review"}'
$id = $thread.id
Invoke-RestMethod "${copilot}?q=alert&archived=false&limit=20&offset=0"
Invoke-RestMethod "$copilot/$id"
Invoke-RestMethod "$copilot/$id/messages?limit=25"
Invoke-RestMethod "$copilot/$id" -Method Patch -ContentType 'application/json' -Body '{"title":"Day shift review","archived":false}'

$requestId = [Guid]::NewGuid().ToString()
$payload = @{ request_id = $requestId; question = 'How is the thermal gap calculated?' } | ConvertTo-Json -Compress
# Pipe the body to curl to preserve JSON quotes in Windows PowerShell.
$payload | curl.exe --no-buffer -H 'Content-Type: application/json' --data-binary '@-' "$copilot/$id/messages/stream"

# Run in a separate terminal with the same conversation and request IDs.
Invoke-RestMethod "$copilot/$id/requests/$requestId/cancel" -Method Post
# Permanently deletes the conversation and messages only, after confirmation.
Invoke-RestMethod "${copilot}/${id}?confirm=$id" -Method Delete
```

The list returns `next_offset` when another page exists. Messages are
returned in chronological order within each page. Pass `next_before_id` as
`before_id` to fetch older messages. Individual conversations have one active
request. A completed request replays the saved answer when the same UUID and
question are submitted again. A conflicting duplicate returns 409. Use a new
UUID to retry a cancelled or failed request. Invalid scope references return
422, missing conversations return 404, and storage failures return 503.
The standalone `POST /api/v1/copilot/chat` contract remains available.

### Streaming and cancellation

The POST stream uses `text/event-stream`. Every event has a name and a JSON
`data` object with matching `type` and `request_id`. An idle connection
receives SSE comments. Configure external reverse proxies to forward the response
without buffering and to allow the configured request deadline.

| Event | Payload and meaning |
| --- | --- |
| `started` | Persisted user message and its selected scope |
| `tool_started`, `tool_completed` | Allowlisted tool name and, on completion, its outcome |
| `evidence` | Count of newly admitted evidence items |
| `clarification` | Signals that the saved reply asks for more specific context |
| `final` | The validated, committed assistant message, including citations and diagnostics |
| `completed` | The saved result was sent |
| `error` | Safe status detail. A provider failure can also carry a saved structured unavailable response. |
| `cancelled` | The request stopped before an assistant reply was committed |

Stop cancels the database reservation. Disconnecting also initiates cleanup.
The provider wait is cancelled and a guarded transaction prevents an already
cancelled request from saving a late reply. If the assistant reply commits
first, it remains available on reload. A disconnected or crashed process can
leave a reservation until its lease expires. A later write releases that
reservation. An upstream provider or an active CPU tool may finish processing
after the API stops waiting. Conversation context sent to the planner is capped
at four saved messages of 600 characters each from the same asset and prediction
scope. Tool and token budgets still apply.

### Readiness and local development limits

The provider status reports disabled, missing credentials, or invalid configuration
before any provider call. It reports configuration separately from upstream
connectivity, which is checked when needed. The workspace also shows an empty
knowledge base and the encoder's cold, initializing, ready, or unavailable state.
Enable optional cached, CPU-only prewarming before starting FastAPI:

```powershell
$env:FLEETMIND_COPILOT_PREWARM = '1'
python -m uvicorn fleetmind.api.main:app --host 127.0.0.1 --port 8000
```

Prewarming runs in a background thread and uses cached or explicitly configured
local files. Ordinary startup keeps the encoder lazy and prewarming never
downloads model weights. Prewarming moves initialization earlier and adds the
encoder's memory cost to each API process that loads it. On a 16 GB machine use
one development worker, especially when a local LLM is also resident.
Use the mock and opt-in live evaluation commands above to measure behavior
with your configured provider.

A Windows smoke benchmark used the cached MiniLM checkpoint, disposable
PostgreSQL 17.10 with pgvector, the starter corpus, and a deterministic mock
provider. With lazy loading, the first thermal-gap response took 19.95 s
and the repeat took 349 ms. With prewarming, the encoder reported readiness
18.13 s after the health endpoint first responded. The first query after
readiness took 282 ms and the repeat took 162 ms. These are single-run timings
through the FastAPI stream, including retrieval and persistence.
Through the production Next.js proxy, the started event arrived in 126 ms
and closing the connection changed the stored request to cancelled in 178 ms.
In the Edge smoke test, a prediction and SHAP answer appeared in 755 ms and
explicit Stop restored the composer in 181 ms.

Signed-in engineers and administrators can access their own Copilot conversations.
Questions and validated replies stay in the database until their conversation is
deleted. Hosted providers receive relevant serialized context and evidence.
Provider credentials and private reasoning are excluded from API responses and
persisted conversations.

Citations retain the exact selected facts. Source inspection loads current registry
or knowledge data by ID. If the cited excerpt was superseded or removed, the stored
quotation remains available and the source inspector reports that the excerpt is
unavailable. Browser and latency checks used a deterministic mock provider with the
real FleetMind tools. Live LLM answer quality, latency, and token usage remain unverified.

## Asynchronous telemetry ingestion

The optional telemetry path sends versioned sensor readings through a
Kafka-compatible broker. The worker validates each event and its registered
asset, runs the same frozen preprocessing and XGBoost pipeline as
`POST /api/v1/predict`, then writes the prediction and a telemetry receipt in
one PostgreSQL transaction. Existing dashboards can read the resulting
predictions through their existing API endpoints.

### Broker choice and startup

Redpanda is the default for local Windows Docker Desktop development. Its
single-node dev-container mode uses one core and a configured 768 MiB memory
budget, with a 1 GiB container limit. The pinned image is
`redpandadata/redpanda:v25.3.11`. Apache Kafka in KRaft mode is also a viable
Kafka-protocol broker without ZooKeeper. Its standard Docker image runs a JVM
and combines broker and controller roles for single-node development. Redpanda
keeps this development profile small and simple. These are configuration
tradeoffs. The memory limits configure the containers. [Redpanda quickstart](https://docs.redpanda.com/streaming/25.3/get-started/quick-start/) and [Apache Kafka Docker documentation](https://kafka.apache.org/41/getting-started/docker/).
For Docker Desktop, allow separate headroom for PostgreSQL and the Linux VM.
The worker runs on the host and loads one copy of the frozen model per process.

```powershell
python -m pip install -r requirements-telemetry.txt
docker compose up -d db
docker compose --profile telemetry up -d --wait broker
```

The broker publishes only its external Kafka listener on
`127.0.0.1:19092`. Its internal Compose endpoint is `broker:9092`.
`FLEETMIND_KAFKA_PORT` changes the host port and advertised address together.
The health check queries Kafka cluster metadata. This profile enables fsync
and disables the dev-container write cache. Broker data uses the separate
`fleetmind_brokerdata` named volume. Regular API startup needs neither the
broker nor the optional Python client.

Check that `DATABASE_URL` targets the intended database, then apply the schema
revision explicitly. Deployment does not automatically run migrations.

```powershell
python -m alembic current
python -m alembic upgrade head
python -m alembic check
```

Revision `0005_telemetry_assessments` adds one receipt table with a unique
event ID and a one-to-one prediction reference. Existing tables, including
predictions without telemetry metadata, keep their original shape.
`GET /api/v1/telemetry/status` reports durable assessment count and latest
ingestion and assessment timestamps. It also reports when the migration is
required. A ready database response does not establish broker connectivity
or worker liveness.

### Commands and event format

Provision the input and dead-letter topics before starting the worker.
Default names are `fleetmind.telemetry.v1` and
`fleetmind.telemetry.dlq.v1`, and the default group is
`fleetmind-inference-v1`. The provisioner requests three input partitions,
one dead-letter partition, and replication factor one. It leaves existing
topics intact. This local profile disables automatic topic creation.

```powershell
python -m scripts.telemetry_worker --create-topics
python -m scripts.telemetry_worker
# Register press-01 and press-02 with the FleetMind asset registry first.
python -m scripts.produce_telemetry --asset press-01 --asset press-02 --rate 10 --count 100 --seed 42 --scenario normal
python -m scripts.produce_telemetry --asset press-01 --rate 50 --duration 5 --seed 42 --scenario stress
```

Run the worker and producer in separate terminals. Ctrl+C stops new work.
The worker lets a successful in-progress assessment reach its offset
acknowledgement and exits without acknowledging unfinished retry work.
Use `--bootstrap`, `--topic`, `--dead-letter-topic`, and `--group`, or
`FLEETMIND_KAFKA_BOOTSTRAP_SERVERS`, `FLEETMIND_TELEMETRY_TOPIC`,
`FLEETMIND_TELEMETRY_DLQ`, and `FLEETMIND_TELEMETRY_GROUP`.

The record key must be the UTF-8 asset ID. Each value is a UTF-8 JSON object
up to 16 KiB. Version 1 requires a UUID, a registered asset ID, a UTC
observation timestamp, a declared source, and the six existing model inputs.
The numeric bounds prevent unsafe model input representations. They do not
establish physical plausibility or authenticated provenance.

```json
{
  "schema_version": 1,
  "event_id": "3308c860-2ba4-4bb8-9253-760b7a4a2b88",
  "asset_id": "press-01",
  "observed_at": "2026-01-06T12:00:00Z",
  "source": "simulated",
  "machine_type": "M",
  "air_temperature_k": 299.5,
  "process_temperature_k": 310.0,
  "rotational_speed_rpm": 1800,
  "torque_nm": 42.75,
  "tool_wear_min": 125
}
```

The simulator cycles through registered assets, seeds the sensor values,
and generates new event IDs and observation timestamps each run. Use
`--rate 0` with a bounded count for a burst. Normal and stress readings are
synthetic inputs for pipeline testing. They do not represent validated
physical degradation. Both sources are caller-declared. A `telemetry` label
provides no independent verification of a device or reading.

### Delivery, retries, and diagnostics

The publisher waits for the broker's delivery callback, uses all-replica
acknowledgement with producer idempotence, and bounds retries and the delivery
deadline. An unconfirmed publish ends that simulator run. Broker replication
factor one provides no redundancy.

The worker handles one offset at a time and acknowledges it synchronously
after the PostgreSQL transaction commits, or after a rejected record is
acknowledged on the dead-letter topic. A crash after database commit and
before Kafka acknowledgement can replay the event. The receipt's unique UUID
prevents duplicate database effects, and a different normalized payload for
the same ID is rejected. Transient database failures get bounded retries.
If they exhaust, or if a broker acknowledgement fails, the worker stops with
the unresolved offset pending. It never advances past that offset. Restart
with the same group after recovery.

Dead letters contain the failure category, original topic, partition and
offset, rejection time, and an event ID when the contract validated. They omit
raw payloads and keys. A crash between DLQ delivery and offset commit can
duplicate a dead letter. Its stable original-location key permits deduplication.
FleetMind does not publish downstream assessment events in this phase.
The design is at-least-once delivery with idempotent prediction effects.

The observation clock is supplied by the producer. Ingestion time records
when the worker polled the ultimately persisted delivery. Assessment time is
assigned after inference, before the commit. Worker JSON diagnostics distinguish
received, processed (new durable assessments), duplicates, invalid records,
retried events, retry attempts, acknowledged dead letters, and committed
offsets. Inference and successful database transaction timings use a
monotonic clock. Observation-to-commit age uses UTC wall clocks, and can be
negative when clocks disagree. Processing duration includes offset
acknowledgement. Lag is the sampled offset backlog for currently assigned
partitions, using librdkafka's non-blocking committed-offset statistics. An unavailable
sample is null. Percentiles use up to the latest 4,096 samples per metric.

### Reproduce the local workload tests

Use a separate PostgreSQL database named `fleetmind_*_test` and a disposable
broker. Migrate the test database to head before running the worker or test
suite. The benchmark creates unique assets, topics, and consumer groups only
on the explicitly supplied disposable services.

```powershell
$env:FLEETMIND_TELEMETRY_TEST_DATABASE_URL = $env:DATABASE_URL
$env:FLEETMIND_TELEMETRY_TEST_BOOTSTRAP = '127.0.0.1:19092'
python -m pytest tests/integration/test_telemetry_broker.py
python -m scripts.benchmark_telemetry --disposable --seconds 5 --burst 250
```

The benchmark measures scheduled 1, 10 and 50 events per second and a bounded
burst. It reports acknowledgement and committed throughput over the observed
window, p50/p95/p99 latency, sampled peak lag, and independently checked final
lag. Windows worker
CPU time and RSS are sampled when the optional `psutil` package is available.
Resource samples include worker startup. Short trials and single-node
durability characterize this local development setup.

### Milestone 10A validation results

The Windows Docker Desktop run used Redpanda 25.3.11, PostgreSQL 17,
one inference worker, eight logical processors, and `OMP_NUM_THREADS=4`.
The [raw benchmark report](reports/telemetry_m10a.json) includes database and
inference timings and resource samples.

| Offered workload | Events | Producer ack/s | Consumer commit/s | Observation-to-DB-commit p50 / p95 / p99 (ms) | Sampled peak lag |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1/s | 5 | 1.25 | 1.24 | 35 / 115 / 115 | 0 |
| 10/s | 50 | 10.19 | 10.13 | 33 / 506 / 658 | 3 |
| 50/s | 250 | 50.00 | 28.17 | 2,099 / 3,737 / 3,850 | 113 |
| Burst | 250 | 155.28 | 27.68 | 3,953 / 6,986 / 7,342 | 207 |

All 555 events were persisted, and independently checked final lag was zero
in every case. At 50/s the single worker accumulated backlog and drained it
after publishing stopped. Throughput is calculated from the start of publishing
and includes the immediate first event, which matters for the five-event trial.
The worker peaked at about 193 MiB RSS. Sampled CPU time, including startup,
ranged from 5.4 to 33.1 seconds across workloads. A separate Docker snapshot
showed 153 MiB for Redpanda and 341 MiB for Apache Kafka KRaft 4.1.2 under their
single-node test configurations. Broker CPU snapshot readings were 0.47% and
2.11%, respectively. These instantaneous samples depend on process activity.

Real-broker tests passed against both Redpanda and Kafka KRaft. They covered the
database-commit/offset-acknowledgement gap, duplicate redelivery, concurrent
inserts, malformed input, missing assets, type mismatches, reused IDs with
changed payloads, a terminated PostgreSQL connection, and graceful shutdown.
The migration test compared legacy table identities and contents before and
after the upgrade.

Use the broker only on trusted local development networks. The Compose
profile is plaintext, and the read-only API status route inherits FleetMind's
local-development security model. Production use needs authenticated producers
and access control, encryption, retention and replay policies, monitoring,
and replicated brokers. Clock skew, partition changes, and producers using
different partitioners can affect cross-stream ordering. The worker preserves
the broker's order within each assigned partition.

## Live Telemetry Command Center

Open `/telemetry` from the dashboard. The page shows committed assessment
history, infrastructure status, worker metrics, and redacted dead-letter reports.
Select an assessment to inspect its event ID, UTC timestamps, original readings,
and SHAP explanation. The drawer links to the registered asset and Copilot.

With the existing PostgreSQL service running, apply the migration explicitly
against the intended database. Start the optional broker and worker as in 10A.

```powershell
python -m alembic current
python -m alembic upgrade head
python -m alembic check
docker compose --profile telemetry up -d --wait broker
python -m scripts.telemetry_worker --create-topics
python -m scripts.telemetry_worker
```

Revision `0006_telemetry_live_monitoring` adds stream records and metrics
tables. It briefly locks inserts into the telemetry receipt table while
backfilling existing receipts. Backfilled cursor order is deterministic by
prediction ID because historical commit order is unavailable. Prediction
IDs, timestamps, and stored inputs are preserved. The trigger also captures
new receipts inserted by a 10A worker after migration. Restart workers with
the 10B code for new diagnostics.

### SSE and reconnect behavior

`GET /api/v1/telemetry/assessments` returns up to 50 recent rows plus the
snapshot cursor. It searches up to the latest 4,096 stream positions and
supports `asset_id` and `alert_level` filters. Open
`GET /api/v1/telemetry/stream?cursor=<cursor>` with the same filters.
`Last-Event-ID` takes precedence over the query cursor. A connection with
neither cursor starts at the current tail. Cursor strings belong to the
current database and feed filter.

| Event | Meaning |
| --- | --- |
| `ready` | Stream established at the given cursor |
| `assessment` | Committed receipt, original prediction, observation, ingestion, and assessment timestamps |
| `cursor` | Advance past scanned positions that did not match the filters |
| `heartbeat` | Keeps an idle stream open every 10 seconds |
| `reset` | Resume cursor is ahead of the current database, so reload the snapshot |
| `unavailable` | Storage or connection capacity is unavailable |

SSE `id` fields are decimal strings. A PostgreSQL trigger creates each
stream row inside the receipt transaction. It updates a shared cursor row,
whose write lock remains held through commit. A later transaction cannot
publish a higher cursor while a lower one is uncommitted. Readers therefore
resume strictly after the last consumed cursor, including when prediction
IDs were allocated in a different order. Event UUIDs deduplicate the browser
feed. The feed replays committed records on reconnect and uses no broker
consumer per client. There is no assessment dual-write to Kafka.

Each connection scans batches of at most 64 cursor positions and waits
500 ms at the tail. Database sessions close before response writes. The API
admits up to 32 telemetry streams per process, limits each write to 10 seconds,
and recycles streams after five minutes. The browser batches updates every
150 ms and keeps up to 60 assessments. Pause holds the displayed feed and
resume replays from its last applied cursor. The dashboard coalesces
stream-triggered refresh requests with a two-second minimum interval between
those batches. Its existing 30-second polling, cancellation, active filters,
pagination, and investigation selection continue to work when the stream is
unavailable.

### Operational metrics and dead letters

`GET /api/v1/telemetry/metrics` combines the durable assessment count and last
assessment timestamp with reported worker data. The worker exports a
checkpoint about every five seconds on a separate thread and connection pool.
The reporter holds one replaceable snapshot. Cumulative counter deltas are
applied once per worker checkpoint and survive worker restarts. They describe
reported processing attempts, including deliveries across all configured
workers and groups. A crash or storage outage can lose unsent measurements.
The PostgreSQL assessment count comes from the durable stream projection and
remains independent of those reports.

| Metric | Definition |
| --- | --- |
| Received, committed | Deliveries polled and Kafka offsets acknowledged, respectively |
| Processed, duplicates, invalid | New durable assessments, recognized redeliveries, and validation rejections |
| Retried events, retry attempts | Deliveries that retried and individual database retry attempts |
| DLQ acknowledgements | Confirmed broker publishes to the dead-letter topic |
| Throughput | Reported counter increments per 10-second bucket, divided by 10. Current partial buckets are also normalized to 10 seconds. |
| Latency | Sample-weighted mean for inference, database persistence, and producer observation to database commit. Clock skew can affect observation age. |
| Backlog | Highest reported lag for one worker's assigned partitions. This gauge can underrepresent the whole group. |
| Worker and broker health | Fresh worker heartbeat and a timestamped worker-side broker metadata probe. Samples older than 20 seconds are stale. |

The rolling view has 30 ten-second buckets and reads at most 3,600 samples
and 64 recent worker checkpoints. A partial query is flagged. Missing series
values appear as gaps. A stopped worker or a stale sample is distinct from
zero readings. Broker status is unknown until a worker has probed it. Existing
committed history and normal FleetMind routes work with the broker turned off.

`GET /api/v1/telemetry/dead-letters` reads recent redacted reports. The worker
copies up to its last 128 acknowledged rejections through the background
reporter. The read-only mirror can miss entries during a burst, crash, or
prolonged storage outage. Kafka is the primary DLQ record. Reports contain
category, rejection time, event ID if known, and topic/partition/offset only.
Samples and mirrored dead letters are pruned in bounded batches after 24 hours.
Per-process checkpoints and cumulative totals are retained. This interface
offers inspection only.

### Reproduce the live workflow

Use the disposable database and broker procedure from Milestone 10A. Apply
revision 0006 on the disposable database, register two test assets, and run a
production Next.js build with `FLEETMIND_API_URL` pointing at that FastAPI
instance. In separate terminals open the feed and submit a finite workload.

```powershell
curl.exe --no-buffer http://127.0.0.1:8000/api/v1/telemetry/stream
python -m scripts.produce_telemetry --asset press-01 --asset press-02 --rate 50 --count 100
```

The browser latency check correlates a timestamp immediately after each
worker transaction returns with that event UUID's first insertion into the
DOM. This includes stream polling, proxy forwarding, browser batching, and
rendering. Use the Developer Tools protocol to measure the production page at
desktop and 320 px, block the stream request to exercise polling fallback,
and compare the metrics totals with the known valid and rejected deliveries.

The [live validation report](reports/telemetry_m10b.json) records a Windows
Docker Desktop run with Redpanda 25.3.11, PostgreSQL, the frozen XGBoost model,
production Next.js, and headless Microsoft Edge.

| Scenario | Measured result |
| --- | --- |
| 100 events offered at 50/s | 100 commit-to-DOM samples. p50 462 ms, p95 688 ms, p99 714 ms. Feed retained 60 rows. |
| Pause and resume | Three missed rows replayed in 407 ms from resume. |
| Blocked stream and automatic reconnect | Two missed rows replayed without duplicates in 2.72 s after unblocking. |
| Dashboard burst | A 20-event burst triggered two summary refreshes. |
| Dashboard with stream blocked | The next polling refresh arrived in 29.99 s. |

The browser spent 1.17 s on renderer tasks during the 10.19 s burst and
checkpoint observation window. It recorded two long tasks of 289 ms and
330 ms, and used 14.4 MiB of JavaScript heap at the sample point. API
working-set samples were 271 MiB before and 274 MiB after the burst. The final
counters matched 127 committed assessments, 128 acknowledged offsets, and one
redacted dead-letter acknowledgement. The manual prediction was preserved.
The browser checks covered filters, the SHAP investigation drawer, and the
320 px layout. These figures are local development measurements.

With Redpanda stopped, a direct FastAPI check held eight idle SSE streams
open, received a heartbeat, and replayed three stored records using
`Last-Event-ID`. Over 10.36 s, 20 metrics requests took 41.56 ms median
and 59.14 ms p95 round trip. The service used 1.52 CPU seconds and its
working set moved from 271.0 to 272.9 MiB during this combined workload.

Telemetry views require a FleetMind session. Keep development database and broker
listeners on loopback. Follow the [deployment requirements](docs/security.md)
for service credentials, TLS, and production network boundaries. Source labels
remain caller-declared, and an uncalibrated failure score requires human review.

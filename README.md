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
Authenticate and authorize Copilot and its model access before deploying beyond
trusted local development.

### Providers and budgets

The server reads these variables from its environment or local `.env`.

| Variable suffix after `FLEETMIND_COPILOT_` | Default / meaning |
| --- | --- |
| `PROVIDER` | `disabled`, `openai`, `ollama`, or `mock` |
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
python -m scripts.evaluate_copilot --live-api http://127.0.0.1:8000 --output reports/copilot_live_local.json
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

Conversation storage is for trusted local development. Conversation IDs segment
requests and history within the application. All clients with access to the API
can currently list, inspect, update, and delete those records. Add authentication,
per-user authorization, operational request limits, and a retention policy before
sharing the service. Questions and validated replies remain in the database until
their conversation is deleted. Hosted providers receive relevant serialized context
and evidence. Provider credentials and private reasoning are excluded from API
responses and persisted conversation data.

Citations retain the exact selected facts. Source inspection loads current registry
or knowledge data by ID. If the cited excerpt was superseded or removed, the stored
quotation remains available and the source inspector reports that the excerpt is
unavailable. Browser and latency checks used a deterministic mock provider with the
real FleetMind tools. Live LLM answer quality, latency, and token usage remain unverified.

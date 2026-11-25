# System architecture

~~~mermaid
flowchart LR
  Person["Browser"] --> Next["Next.js secure workspace"]
  Next -->|Same-origin bridge| FastAPI["FastAPI authorization and services"]
  FastAPI --> Model["Frozen preprocessing and XGBoost"]
  FastAPI --> DB[("PostgreSQL 17 and pgvector")]
  Operator["Seeded simulator"] --> Broker["Redpanda"]
  Broker --> Worker["Inference worker"]
  Worker --> Model
  Worker --> DB
  DB -->|Committed change feed| FastAPI
  FastAPI -->|SSE| Next
  FastAPI --> Retriever["Hybrid knowledge retrieval"]
  Retriever --> DB
  Worker -.-> Metrics["Private Prometheus and Grafana"]
  FastAPI -.-> Metrics
~~~

## Local and portfolio profiles

~~~mermaid
flowchart TD
  Local["Local Next.js build"] --> Auth["Session gate, API bridge and CSRF"]
  Auth --> DB["Private database and full workflows"]
  Public["Vercel portfolio build"] --> Snapshot["Simulated assets, actual scores, precomputed SHAP, scripted Copilot"]
  Public --> Playback["Bounded browser playback of the recorded sequence"]
  Public -.-> Bridge["Same-origin POST /demo/infer bridge"]
  Bridge -.-> Render["Optional stateless frozen CPU inference on Render"]
~~~

The public API bridge has a single inference route and returns 404 for local API paths. The public build cannot load a local session or connect to the private database. The records come from the reproducible fixture generator. Its model and benchmark inputs come from tracked artifacts and reports.

## Storage and data ownership

Alembic revisions live under [migrations](../migrations/versions). Predictions preserve original inputs, source and model version. An optional asset foreign key leaves legacy rows valid. Knowledge documents, chunks and embedding metadata support content-addressed ingestion. Copilot stores conversations, messages and execution diagnostics scoped to owners. Security tables contain accounts, session token digests, service credentials and audit events. Telemetry stores source event IDs, timing, processing observations and delivery diagnostics. The model health revision indexes the source- and version-scoped assessment window.

## Telemetry commit sequence

~~~mermaid
sequenceDiagram
  participant S as Simulator
  participant B as Broker
  participant W as Consumer
  participant P as PostgreSQL
  participant F as SSE feed
  S->>B: Publish versioned reading keyed by asset ID
  B->>W: Deliver event
  W->>W: Validate event and score frozen model
  W->>P: Insert assessment by unique source event ID
  P-->>W: Commit or report duplicate
  W->>B: Acknowledge durable handling by offset
  P-->>F: Read committed assessments by cursor
~~~

A crash between database commit and offset acknowledgement can replay a delivery. The unique source event constraint protects the prediction history. The worker retries transient failures in order and publishes permanently invalid events to a bounded dead-letter topic before committing their offsets. See [telemetry contracts, retry rules and benchmark methods](operations.md#asynchronous-telemetry-ingestion).

## Copilot evidence flow

~~~mermaid
flowchart LR
  Ask["Question and authorized scope"] --> Plan["Bounded orchestration"]
  Plan --> Tools["Typed read-only model, history and retrieval tools"]
  Tools --> Fuse["Vector and PostgreSQL FTS ranks with RRF"]
  Tools --> Evidence["Validate source references and result scope"]
  Fuse --> Evidence
  Evidence --> Answer["Answer with citations or abstain"]
  Answer --> Save["Save final result within conversation owner scope"]
~~~

The checked-in [knowledge corpus](knowledge/) uses attributed project documentation and general review guidance. Content hashing and persistent chunk identifiers support citations and idempotent updates. Retrieved text and conversation history are untrusted evidence. [Operations](operations.md#maintenance-knowledge-base) covers ingestion, ranking, evaluation and provider setup.

## Session lifecycle

~~~mermaid
sequenceDiagram
  participant U as Browser
  participant N as Next.js bridge
  participant A as FastAPI
  participant D as Security store
  U->>N: Credentials and exact Origin
  N->>A: Allowlisted login request
  A->>D: Verify Argon2id and create opaque session digest
  A-->>U: HttpOnly session cookie and CSRF cookie
  U->>N: Session plus Origin and CSRF header on writes
  N->>A: Forward allowed headers
  A->>D: Verify active session, role and resource ownership
  A-->>U: Authorized result or rejection
~~~

[SSE revocation, role permissions and deployment boundaries](security.md) · [Lineage and monitoring](mlops.md)

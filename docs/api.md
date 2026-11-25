# API reference

The full FastAPI application uses `/api/v1` for application routes. The browser uses the Next.js same-origin `/api/fleetmind` bridge. The route table and Pydantic schemas are in [source](../src/fleetmind/api); the backend remains the authorization authority. JSON inputs use explicit read/source units and the contracts are covered by the integration suite.

| Routes | Purpose |
| --- | --- |
| `GET /health`; `GET /api/v1/system/status` | Public liveness; authenticated readiness |
| `POST /api/v1/auth/login`; `GET /api/v1/auth/me` | Origin-checked sign-in; current identity |
| `/api/v1/auth/logout`, `/password`, `/sessions` | Own credentials and session lifecycle |
| `GET /api/v1/dashboard/summary`; `GET /api/v1/dashboard/trends` | Counts and time buckets |
| `POST /api/v1/predict` | Authorized persisted assessment, with optional asset ID and declared source |
| `GET /api/v1/predictions`; `/predictions/{id}`; `/predictions/{id}/explanation` | Filtered history, original inputs and version-checked SHAP |
| `/api/v1/assets`; `/assets/{asset_id}`; `/assets/{asset_id}/{predictions,summary}` | Registry, updates and per-asset history and counts |
| `GET /api/v1/model/intelligence`; `GET /api/v1/model/health` | Model metadata and source-scoped drift over bounded time windows |
| `/api/v1/knowledge/{status,documents,search}` | Corpus inspection, evidence and bounded hybrid retrieval |
| `/api/v1/copilot/conversations` and subroutes | Own conversations, messages, SSE and cancellation |
| `GET /api/v1/telemetry/{status,assessments,metrics,stream,dead-letters}` | Committed stream, storage and worker diagnostics |
| `/api/v1/admin/*` | Administrator-only account, credential, audit and legacy data operations |
| `GET /metrics` | Token-protected local monitoring export |

Read endpoints generally use bounded limit and offset. The committed assessment SSE endpoint supports cursor resumption. Mutations enforce roles and cookie-bound CSRF. Service tokens are scoped and independently revocable. See the [permission matrix](security.md#permission-matrix) and [concrete requests](operations.md).

## Hosted profile

The separate [portfolio app](../src/fleetmind/hosted.py) exposes `GET /health` and `POST /infer`. The web bridge exposes only `POST /api/fleetmind/demo/infer`. A reading is JSON with `machine_type` (L, M or H), `air_temperature_k`, `process_temperature_k`, `rotational_speed_rpm`, `torque_nm` and `tool_wear_min`. The response includes `model_version`, `failure_score`, `predicted_failure` and `alert_level`.

The hosted API returns 413 for oversized uploads, 415 for incorrect media type, 422 for invalid values, and 429 with Retry-After when its shared budget or slot is exhausted. The bridge returns a bounded 503 for cold, unavailable or invalid upstream responses. No assessments are persisted. Local users continue using the authenticated APIs.

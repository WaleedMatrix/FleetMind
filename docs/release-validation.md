# Release validation

The candidate was validated locally using Windows, Python 3.11, Node.js 22, Edge, Docker Desktop, PostgreSQL 17 with pgvector, and Redpanda. Provider deployment, remote CI, and live provider Copilot evaluation are pending owner approval and authorized access.

| Check | Result |
| --- | --- |
| Python, including existing database, security and broker integration tests | 97 passing |
| Frontend bridge tests | 7 passing, covering full and portfolio boundaries |
| Scripted Copilot | 51 passing, with zero case failures |
| Ruff, ESLint, TypeScript | Passing |
| Next.js production builds | Secured local and read-only portfolio |
| Migration validation | Disposable PostgreSQL at `0008_model_health_lookup`; Alembic schema check clean |
| Native local API | Health, unauthorized 401, sign-in, CSRF 403, 4 simulated assets, 48 matching inference scores, SHAP and model metadata |
| Portfolio data | 144 frozen-model assessments, with a byte-identical repeat build of the fixture |
| Dataset | Existing AI4I CSV matched the frozen hash. Fresh UCI downloads timed out in this environment. |
| Browser | Dashboard, asset registry/detail, alert explanation, model intelligence/health, scripted Copilot, playback, outage fallback, live scoring through the bridge, mobile width, and a separate sign-in and Grafana capture |

## Re-run results on the checked-in knowledge corpus

The same 32-query regression suite includes 28 answerable and four out-of-domain questions; 384-dimensional MiniLM on the pinned CPU environment. The first seed inserted eight documents and 18 chunks in 40.4 s including cold model load and commit. The separate retrieval run took 19.7 s to warm the encoder. Timing varies with CPU contention and cache state.

| Mode | Recall@5 | MRR | nDCG@5 | p95 request time |
| --- | ---: | ---: | ---: | ---: |
| Semantic | 0.988095 | 0.928571 | 0.933875 | 76.08 ms |
| Keyword | 0.142857 | 0.142857 | 0.142857 | 15.46 ms |
| Hybrid | 0.988095 | 0.946429 | 0.947057 | 66.24 ms |

Semantic and hybrid both returned candidates for the four out-of-domain questions. The historical regression corpus and source filters limit generalization. RRF scores rank candidates. Calibrated confidence would require additional evaluation. [Raw release run](../reports/knowledge_retrieval_v1.json) · [Retrieval methods](operations.md#maintenance-knowledge-base) · [Further retrieval and performance reports](mlops.md)

## Optional stateless inference

The Linux x86-64 image installed the exact pinned package set from verified PyPI wheels after the in-container network request timed out. The Docker Desktop run used a read-only filesystem, UID 10001, one Uvicorn worker, 0.1 CPU and 512 MiB without additional swap. The image exposes only health and bounded inference. The installed package directory used 399 MiB of disk. Neither PyTorch, Transformers, Sentence Transformers, SHAP, PostgreSQL clients, Redpanda clients, MLflow nor LLM SDKs were present or imported after actual model scoring.

| Measurement | Observed |
| --- | ---: |
| Peak process RSS after the 29-request run | 188.0 MiB |
| Peak container memory after the 29-request run | 128.5 MiB |
| Warm loopback p50 / p95 / max | 104.95 / 198.47 / 200.09 ms |
| Frozen score equivalence | 29 exact scores and matching alert tiers and binary decisions |
| Shared process request budget | HTTP 429 and Retry-After after 30 permits |
| Cold start of the final image with one-tenth CPU | 106.1 s from launch to ready response |
| Second isolated start with one visible core and no Docker health probe | 80.8 s from launch to ready response |

The first trial with a Python-based health check took 257.3 s from container start to the ready log. The final image uses a lightweight shell probe. Cold startup varied substantially and exceeded the 30-second frontend request deadline. [Raw final measurement](../reports/portfolio_runtime_v1.json) Start with the recorded Vercel profile. The optional Render endpoint needs a real provider smoke test before it is connected to the public deployment. These local measurements do not estimate Render's startup or availability. The constrained service received no browser credentials and made no database connection.

To reproduce the warm equivalence, latency and rate test against a fresh running local container, run:

~~~powershell
python -m scripts.validate_portfolio_runtime --port 19983
~~~

## Frozen artifact verification

~~~text
8dcaddd194de846612b68fa42e34171003cc24457faaddad1f6c5c33ce0978f6  xgboost_v1.joblib
fd209f1abe9837a202747803b5f07c350d7dc0502c16d6a9de56e795bae0e3de  xgboost_v1.metadata.json
~~~

[Security findings and release gates](security-release.md) · [Deployment and owner verification](deployment.md)

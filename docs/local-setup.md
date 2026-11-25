# Full local setup

FleetMind uses Python 3.11, Node.js 22, Docker Desktop with Linux containers, and PostgreSQL 17 with pgvector. With 16 GB RAM, start the database and the optional services you need. The authenticated dashboard, inference, assets, investigation and SHAP require the database. The portfolio build requires only Node.js.

## Install and start

From the repository root in PowerShell, prepare the environment with a new strong local password. Update both password fields in the copied environment file. URL-encode password characters in the connection URL.

~~~powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt -e .
python -m scripts.verify_frozen_artifacts
Copy-Item .env.example .env
docker compose up -d db
python -m alembic upgrade head
python -m alembic current
python -m scripts.manage_security bootstrap --username local-admin
python -m uvicorn fleetmind.api.main:app --host 127.0.0.1 --port 8000
~~~

The bootstrap CLI prompts for the initial password. In a separate terminal inside `frontend`, copy `.env.example` to `.env.local` and run:

~~~powershell
npm.cmd ci
npm.cmd run dev -- --hostname 127.0.0.1
~~~

Open `http://127.0.0.1:3000/login`. If authentication fails, check the API port, database revision, and exact browser origin. `GET /health` checks liveness. Signed-in `GET /api/v1/system/status` checks model availability. If the model fails verification, recover the checked-in artifacts and check the hashes before restarting.

## Existing PostgreSQL installation

The owner's local revision was `0007_application_security` when the release work began. Release validation used a disposable database. The portfolio does not connect to either database. To opt in to Model Health on your local installation, take and verify a private PostgreSQL backup first, check `DATABASE_URL`, then run `python -m alembic upgrade 0008_model_health_lookup` and `python -m alembic current`. Revision 0008 adds a prediction lookup index to the existing tables. The read-only revision check also reported an OS collation version mismatch on the owner database. Review the OS and PostgreSQL pairing before scheduling maintenance. Schedule an appropriate maintenance window for larger histories. Keep the existing named volume. Never use `docker compose down -v` to upgrade it.

## Optional features and validation

Run `python -m scripts.fetch_ai4i` before reproducing training or tests that load the raw dataset. The running application uses the frozen artifacts directly.

- [Operations](operations.md) covers knowledge and the MiniLM cache, Copilot providers, simulation, Redpanda, worker commands, SSE and failure handling. Seed only the checked-in corpus and keep demo recordings separate from operational data.
- [MLOps](mlops.md) covers training lineage, drift, optional local MLflow, Prometheus and Grafana, and reproducible benchmarks.
- [Testing and contributions](../CONTRIBUTING.md) gives disposable database and regression commands.
- [Security](security.md) describes browser origins, account roles, CSRF, credential rotation and service identity.
- If the shared development ports are in use, choose an unused loopback port, update the appropriate origin and frontend bridge target, and restart only the affected development process.

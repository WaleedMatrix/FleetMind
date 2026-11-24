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
   revision is `0002_asset_intelligence`.

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

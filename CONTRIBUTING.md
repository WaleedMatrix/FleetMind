# Contributing

Read [local setup](docs/local-setup.md) before starting. Keep trained artifacts and experiment outputs intact. Use seeded synthetic tests, preserve provenance and validate changes in an isolated environment.

## Validate

Create a disposable PostgreSQL 17 database with pgvector and a name ending in `_test`. Set `DATABASE_URL` and `FLEETMIND_MIGRATION_TEST_DATABASE_URL` to that instance. Never set migration or telemetry integration test variables to a user database. To include real broker tests, use the [separate telemetry test environment](docs/operations.md#asynchronous-telemetry-ingestion).

~~~powershell
python -m pip check
python -m scripts.fetch_ai4i
python -m scripts.verify_frozen_artifacts
ruff check .
python -m alembic upgrade head
python -m alembic check
python -m pytest
python -m scripts.evaluate_copilot
~~~

From `frontend`, run `npm.cmd ci`, `npm.cmd run lint`, `npm.cmd run test:proxy`, `npm.cmd run build`, and `npx.cmd tsc --noEmit`. Repeat the build with `NEXT_PUBLIC_FLEETMIND_MODE=portfolio`. Standard CI uses no live LLM account.

Regenerate recorded fixtures with `python -m scripts.generate_portfolio` from the Git root. It creates private in-memory SQLite stores. Imports require a valid `DATABASE_URL` value, so set it to the disposable validation database. Review the fixture diff for data provenance and inspect the main views before committing. Follow [deployment approval and tagging](docs/deployment.md#release-approval) for public releases.

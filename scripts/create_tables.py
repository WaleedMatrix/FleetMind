"""Apply FleetMind database migrations for local development."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from fleetmind.db.database import engine


def main():
    print("=== FLEETMIND DATABASE INITIALIZATION ===")

    config = Path(__file__).resolve().parents[1] / "alembic.ini"
    command.upgrade(Config(config), "head")

    inspector = inspect(engine)

    print("\nAvailable tables:")

    for table_name in inspector.get_table_names():
        print(f" - {table_name}")

    if "prediction_history" not in inspector.get_table_names():
        raise RuntimeError("prediction_history table was not created.")

    print("\nDatabase initialization successful!")


if __name__ == "__main__":
    main()

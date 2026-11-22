"""Create FleetMind database tables for local development."""

from sqlalchemy import inspect

from fleetmind.db.database import Base, engine
from fleetmind.db.models import PredictionHistory  # noqa: F401


def main():
    print("=== FLEETMIND DATABASE INITIALIZATION ===")

    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)

    print("\nAvailable tables:")

    for table_name in inspector.get_table_names():
        print(f" - {table_name}")

    if "prediction_history" not in inspector.get_table_names():
        raise RuntimeError("prediction_history table was not created.")

    print("\nDatabase initialization successful!")


if __name__ == "__main__":
    main()

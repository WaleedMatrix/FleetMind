"""Verify FleetMind PostgreSQL connectivity."""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text


def main():
    load_dotenv()

    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError("DATABASE_URL is missing from your .env file.")

    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )

    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT current_database(), current_user"))

            database, user = result.one()

            print("=== FLEETMIND DATABASE CONNECTION ===")
            print(f"Database: {database}")
            print(f"User: {user}")
            print("Connection successful!")

    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

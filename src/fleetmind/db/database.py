"""PostgreSQL connection and SQLAlchemy session management."""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import (
    DeclarativeBase,
    sessionmaker,
)

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing. Add it to your project .env file.")


class Base(DeclarativeBase):
    """Base class for all FleetMind database models."""


engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


def get_db():
    """Provide a database session and close it afterward."""

    with SessionLocal() as session:
        yield session

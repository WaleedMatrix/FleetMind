"""Isolated security storage and real sign-in helpers for API tests."""

from contextlib import contextmanager
from functools import lru_cache

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from fleetmind.api.main import app
from fleetmind.security.models import (
    AuditEvent,
    AuthSession,
    ServiceCredential,
    UserAccount,
)
from fleetmind.security.protect import Limits
from fleetmind.security.settings import SecuritySettings
from fleetmind.security.store import HASHER, SecurityStore

ORIGIN = "http://testserver"
PASSWORD = "Valid-fixture-password"


@lru_cache(maxsize=1)
def fixture_hash():
    return HASHER.hash(PASSWORD)


@pytest.fixture
def seed_account():
    def seed(factory, username="engineer-test", role="engineer"):
        with factory.begin() as db:
            existing = db.scalar(
                select(UserAccount).where(UserAccount.username == username)
            )
            if existing:
                return existing.id
            user = UserAccount(
                username=username, role=role, password_hash=fixture_hash()
            )
            db.add(user)
            db.flush()
            return user.id

    return seed


@pytest.fixture
def auth_database():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    tables = [
        UserAccount.__table__,
        AuthSession.__table__,
        AuditEvent.__table__,
        ServiceCredential.__table__,
    ]
    UserAccount.metadata.create_all(engine, tables=tables)
    try:
        yield sessionmaker(engine, expire_on_commit=False)
    finally:
        engine.dispose()


@pytest.fixture
def install_auth(auth_database, monkeypatch):
    def install(factory=None):
        store = SecurityStore(factory or auth_database)
        monkeypatch.setitem(app.state._state, "security_store", store)
        monkeypatch.setitem(
            app.state._state,
            "security_settings",
            SecuritySettings(frozenset({ORIGIN}), True),
        )
        monkeypatch.setitem(app.state._state, "security_limits", Limits())
        return store

    return install


@pytest.fixture
def sign_in():
    def login(client, username="engineer-test", *, password=PASSWORD):
        response = client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
            headers={"Origin": ORIGIN},
        )
        if response.status_code == 200:
            client.headers.update(
                {"Origin": ORIGIN, "X-FleetMind-CSRF": client.cookies["fleetmind_csrf"]}
            )
        return response

    return login


@pytest.fixture
def auth_client(install_auth, seed_account, sign_in):
    @contextmanager
    def client(factory=None, username="engineer-test", role="engineer"):
        store = install_auth(factory)
        seed_account(store.factory, username, role)
        with TestClient(app) as http:
            logged_in = sign_in(http, username)
            assert logged_in.status_code == 200, logged_in.text
            yield http

    return client

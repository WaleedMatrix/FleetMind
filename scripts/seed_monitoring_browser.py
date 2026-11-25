"""Seed one local browser benchmark fixture in a migrated disposable database."""

import os

from sqlalchemy import select, text

from fleetmind.db.models import Asset
from fleetmind.security.models import UserAccount
from fleetmind.security.store import SecurityStore

store = SecurityStore()
with store.factory() as db:
    name = db.scalar(text("SELECT current_database()"))
    if not (name.startswith("fleetmind_m11b_browser") and name.endswith("_test")):
        raise SystemExit("Use a dedicated disposable browser database.")
    existing = db.scalar(select(UserAccount.id).limit(1))

if existing is None:
    store.create_user(
        "browser-bench",
        os.environ["FLEETMIND_BROWSER_FIXTURE_PASSWORD"],
        "administrator",
    )
with store.factory.begin() as db:
    asset = Asset(
        asset_id="browser-press",
        display_name="Benchmark fixture press",
        machine_type="L",
    )
    if db.get(Asset, asset.asset_id) is None:
        db.add(asset)

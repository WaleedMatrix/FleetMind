from alembic import context

from fleetmind.copilot.conversation_models import Base
from fleetmind.db import models  # noqa: F401
from fleetmind.db.database import engine
from fleetmind.knowledge.models import KnowledgeBase

metadata = [Base.metadata, KnowledgeBase.metadata]

if context.is_offline_mode():
    context.configure(url=engine.url, target_metadata=metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:

    def run_migrations(connection):
        context.configure(connection=connection, target_metadata=metadata)
        with context.begin_transaction():
            context.run_migrations()

    connection = context.config.attributes.get("connection")
    if connection is not None:
        run_migrations(connection)
    else:
        with engine.connect() as connection:
            run_migrations(connection)

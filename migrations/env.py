from alembic import context

from fleetmind.db.database import engine
from fleetmind.db.models import Base

if context.is_offline_mode():
    context.configure(url=engine.url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:

    def run_migrations(connection):
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()

    connection = context.config.attributes.get("connection")
    if connection is not None:
        run_migrations(connection)
    else:
        with engine.connect() as connection:
            run_migrations(connection)

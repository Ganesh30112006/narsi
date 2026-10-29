"""Alembic environment. Uses DATABASE_URL from application settings."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection

import app.db.models  # noqa: F401  (registers every table on Base.metadata)
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import build_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    return config.attributes.get("database_url") or get_settings().database_url


def run_migrations_offline() -> None:
    url = _url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        render_as_batch=url.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _url()
    connectable = config.attributes.get("connection")
    if connectable is None:
        engine = build_engine(url)
        with engine.connect() as connection:
            _run(connection, url)
        engine.dispose()
    else:
        _run(connectable, url)


def _run(connection: Connection, url: str) -> None:
    sqlite = url.startswith("sqlite")
    if sqlite:
        # Batch migrations rebuild a table (copy → drop → rename). SQLite must not enforce foreign keys midway, or
        # dropping a referenced table fails; integrity is checked once the migration has finished instead.
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()  # end the implicit transaction, or Alembic's would nest inside it and never commit
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=sqlite,
    )
    with context.begin_transaction():
        context.run_migrations()
    if sqlite:
        problems = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()
        if problems:
            raise RuntimeError(f"Foreign key violations after migration: {problems[:5]}")


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

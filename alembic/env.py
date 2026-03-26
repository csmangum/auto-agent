"""Alembic environment for claims database migrations.

Uses settings (CLAIMS_DB_PATH env or default data/claims.db).

When invoked programmatically (e.g. from :func:`claim_agent.db.database._run_alembic_migrations`),
the caller may set ``sqlalchemy.url`` in the :class:`alembic.config.Config` object to supply the
database URL directly.  When that option contains a real URL (not the ini-file placeholder
``driver://user:pass@localhost/dbname``), this environment uses it as-is, avoiding the import of
``claim_agent.db.database`` (and its heavy dependency chain) at migration time.
"""
from logging.config import fileConfig

from sqlalchemy import create_engine
from sqlalchemy import pool

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None

# Alembic ini placeholder – used when no real URL has been configured.
_INI_PLACEHOLDER = "driver://user:pass@localhost/dbname"


def get_url() -> str:
    """Return the database URL.

    Preference order:
    1. ``sqlalchemy.url`` already set in the Alembic config (e.g. by programmatic callers).
    2. ``_get_database_url()`` from :mod:`claim_agent.db.database` (CLI / env-var path).
    """
    configured = config.get_main_option("sqlalchemy.url", default=None)
    if configured and configured != _INI_PLACEHOLDER:
        return configured
    from claim_agent.db.database import _get_database_url

    return _get_database_url()


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(
        get_url(),
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

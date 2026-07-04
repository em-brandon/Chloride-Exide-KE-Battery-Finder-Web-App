"""
Alembic environment configuration.

- Reads DATABASE_URL from the .env file (via python-dotenv).
- Imports all SQLAlchemy models so that autogenerate can detect changes.
- Supports both online (connected) and offline (SQL-script) migrations.
"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

# ---------------------------------------------------------------------------
# Ensure the backend directory is on sys.path so we can import db and models.
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Load .env (lives at the repo root, one level above backend/) before
# importing db (which reads DATABASE_URL at import time).
load_dotenv(ROOT.parent / ".env")

# Import Base and all models so autogenerate can see them.
from db import Base       # noqa: E402
import models             # noqa: E402, F401  — registers models on Base.metadata

# ---------------------------------------------------------------------------
# Alembic Config object — gives access to alembic.ini values.
# ---------------------------------------------------------------------------
config = context.config

# Inject the real DATABASE_URL from the environment.
config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])

# Set up Python logging from alembic.ini.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The metadata object that autogenerate compares against.
target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Offline migration (generates a SQL script without a live DB connection).
# ---------------------------------------------------------------------------
def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online migration (connects to the DB and applies migrations directly).
# ---------------------------------------------------------------------------
def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

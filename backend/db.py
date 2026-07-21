"""
SQLAlchemy engine and session factory.

All other modules import `engine` or `SessionLocal` from here.
The DATABASE_URL is read from the environment. In production, ECS injects it
(and other secrets) directly as real environment variables from AWS SSM
Parameter Store / Secrets Manager — see README's Production Architecture.

`public_engine`/`PublicSessionLocal` are a second, least-privilege connection
for the public (unauthenticated) request path — bound to a restricted
Postgres role (`batteryfinder_public`, created by migration
20260721_c4d5e6f7a8b9) that can only read the matcher's source tables and
write to the small set of tables public routes actually touch. `app.py`'s
public routes and `matcher.py` use this; admin routes and pipelines keep
using `engine`/`SessionLocal`, which stays bound to the full-privilege role.
"""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# override=False: real environment variables (e.g. secrets ECS injects in
# production) always win. .env only fills in variables that aren't already
# set, so a stray .env in a production image can never clobber a real secret.
load_dotenv(override=False)

_DATABASE_URL = os.environ.get("DATABASE_URL")
if not _DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set. "
        "Create a .env file at the repo root with your connection string "
        "(see README.md's Environment Variables section)."
    )

engine = create_engine(
    _DATABASE_URL,
    pool_pre_ping=True,   # drops stale connections before use
    pool_size=10,
    max_overflow=15,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

_PUBLIC_DATABASE_URL = os.environ.get("PUBLIC_DATABASE_URL")
if not _PUBLIC_DATABASE_URL:
    raise RuntimeError(
        "PUBLIC_DATABASE_URL environment variable is not set. "
        "Create a batteryfinder_public Postgres role (see the "
        "20260721_c4d5e6f7a8b9 migration) and add a connection string for it "
        "to .env (see README.md's Environment Variables section)."
    )

public_engine = create_engine(
    _PUBLIC_DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=15,
)

PublicSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=public_engine)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass

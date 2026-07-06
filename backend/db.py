"""
SQLAlchemy engine and session factory.

All other modules import `engine` or `SessionLocal` from here.
The DATABASE_URL is read from the environment. In production, ECS injects it
(and other secrets) directly as real environment variables from AWS SSM
Parameter Store / Secrets Manager — see README's Production Architecture.
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


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass

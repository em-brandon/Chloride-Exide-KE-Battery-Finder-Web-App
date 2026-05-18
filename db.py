"""
SQLAlchemy engine and session factory.

All other modules import `engine` or `SessionLocal` from here.
The DATABASE_URL is read from the environment (loaded from .env by python-dotenv).
"""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

load_dotenv()

_DATABASE_URL = os.environ.get("DATABASE_URL")
if not _DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set. "
        "Copy .env.example to .env and fill in your connection string."
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

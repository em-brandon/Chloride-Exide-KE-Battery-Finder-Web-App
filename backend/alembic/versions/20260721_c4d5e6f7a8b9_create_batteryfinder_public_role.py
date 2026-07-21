"""create least-privilege batteryfinder_public role

Revision ID: c4d5e6f7a8b9
Revises: a3b4c5d6e7f8
Create Date: 2026-07-21
"""
import os

from alembic import op

revision = 'c4d5e6f7a8b9'
down_revision = 'a3b4c5d6e7f8'
branch_labels = None
depends_on = None

_ROLE = "batteryfinder_public"

# Tables the restricted role may only ever read: the matcher's 7 source
# tables, plus app_settings (maintenance-mode check on every request) and
# test_users (read on every login attempt — write access granted separately
# below, since registration also needs to insert into it).
_SELECT_ONLY_TABLES = [
    "vehicle_years",
    "vehicle_years_exide",
    "battery_specs",
    "dial_battery_inference",
    "oem_fitment",
    "web_battery_validation",
    "model_aliases",
    "app_settings",
]

# Tables public routes write to. Granted SELECT as well as INSERT/UPDATE —
# not just for reads (e.g. the login lookup on test_users), but because
# Postgres also requires SELECT on: (a) any column returned by SQLAlchemy's
# implicit RETURNING after an INSERT (used to read back server-generated
# ids), and (b) any column referenced in an UPDATE's WHERE clause (the
# by-id row lookup in _flush_read_counter/_get_test_user_from_token).
# UPDATE is granted table-wide rather than column-restricted for the same
# reason — a column-level grant only covers the SET list, not the WHERE
# clause, so it would need a matching SELECT grant on "id" anyway.
_READ_WRITE_TABLES = [
    "search_events",
    "user_feedback",
    "test_users",
    "test_user_sessions",
    "admin_stats",
]


def upgrade() -> None:
    password = os.environ.get("PUBLIC_DB_PASSWORD")
    if not password:
        raise RuntimeError(
            "PUBLIC_DB_PASSWORD environment variable is not set. Set it to "
            "the password the batteryfinder_public role should be created "
            "(or re-set) with before running this migration — see "
            "README.md's Environment Variables section."
        )
    escaped_password = password.replace("'", "''")

    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{_ROLE}') THEN
                CREATE ROLE {_ROLE} LOGIN PASSWORD '{escaped_password}';
            ELSE
                ALTER ROLE {_ROLE} LOGIN PASSWORD '{escaped_password}';
            END IF;
        END
        $$;
        """
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            EXECUTE format('GRANT CONNECT ON DATABASE %I TO {_ROLE}', current_database());
        END
        $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {_ROLE}")

    for table in _SELECT_ONLY_TABLES:
        op.execute(f"GRANT SELECT ON {table} TO {_ROLE}")

    for table in _READ_WRITE_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {_ROLE}")
        op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {table}_id_seq TO {_ROLE}")


def downgrade() -> None:
    for table in _READ_WRITE_TABLES:
        op.execute(f"REVOKE ALL ON SEQUENCE {table}_id_seq FROM {_ROLE}")
        op.execute(f"REVOKE ALL ON {table} FROM {_ROLE}")
    for table in _SELECT_ONLY_TABLES:
        op.execute(f"REVOKE ALL ON {table} FROM {_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {_ROLE}")
    op.execute(
        f"""
        DO $$
        BEGIN
            EXECUTE format('REVOKE CONNECT ON DATABASE %I FROM {_ROLE}', current_database());
        END
        $$;
        """
    )
    op.execute(f"DROP ROLE IF EXISTS {_ROLE}")

"""convert vehicle_years_exide from a table to a live view over oem_fitment

vehicle_years_exide was a manually-loaded table, TRUNCATE+reloaded only when
pipelines/exide_fitment_clean.py was run by hand. That left it silently stale
after any other change to oem_fitment (e.g. a direct data-quality fix) until
someone remembered to re-run the pipeline. Converting it to a view removes
that failure mode entirely — a view has no stored rows to go stale; every
query recomputes it from oem_fitment's current state.

Revision ID: 3278f8c1b881
Revises: 6e114cfe6168
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa

revision = "3278f8c1b881"
down_revision = "6e114cfe6168"
branch_labels = None
depends_on = None

_PUBLIC_ROLE = "batteryfinder_public"

# Mirrors pipelines/exide_fitment_clean.py's old model-display stripping
# (formerly _strip_chassis_code_suffix / _TRAILING_PAREN_RE, now removed from
# that file since this view is the only place the logic runs) and its
# year-range-to-existence-rows explosion (formerly done in Python once per
# pipeline run, now live). LEAST(..., current year) caps every range at the
# current year — including explicit year_to values beyond it, not just
# open-ended ("PRESENT") ones — matching the original pipeline's behavior
# exactly. Using EXTRACT(YEAR FROM now()) instead of a hardcoded constant
# means this never needs a yearly bump like the old CURRENT_YEAR did.
_VIEW_SQL = r"""
    CREATE VIEW vehicle_years_exide AS
    SELECT DISTINCT ON (make, stripped_model, y.year)
        make,
        stripped_model AS model,
        y.year AS year,
        cylinder_capacity_cc AS engine_capacity,
        NULL::varchar(50) AS fuel
    FROM (
        SELECT make, cylinder_capacity_cc, year_from, year_to,
               regexp_replace(model, '\s*\([^)]*\)?\s*$', '') AS stripped_model
        FROM oem_fitment
        WHERE ah IS NOT NULL
    ) s,
    LATERAL generate_series(
        year_from,
        LEAST(COALESCE(year_to, EXTRACT(YEAR FROM now())::int), EXTRACT(YEAR FROM now())::int)
    ) AS y(year)
    ORDER BY make, stripped_model, y.year, cylinder_capacity_cc NULLS LAST
"""


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS vehicle_years_exide")
    op.execute(_VIEW_SQL)
    # Grants are tied to the specific relation and don't survive DROP TABLE +
    # CREATE VIEW under the same name — re-grant explicitly (mirrors the
    # SELECT grant given to the old table in create_batteryfinder_public_role).
    op.execute(f"GRANT SELECT ON vehicle_years_exide TO {_PUBLIC_ROLE}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS vehicle_years_exide")
    op.create_table(
        "vehicle_years_exide",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("make", sa.String(100), nullable=False),
        sa.Column("model", sa.String(300), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("engine_capacity", sa.Integer(), nullable=True),
        sa.Column("fuel", sa.String(50), nullable=True),
        sa.UniqueConstraint("make", "model", "year", name="uq_vehicle_years_exide"),
    )
    op.create_index("ix_vehicle_years_exide_make", "vehicle_years_exide", ["make"])
    op.create_index("ix_vehicle_years_exide_make_model", "vehicle_years_exide", ["make", "model"])
    op.execute(f"GRANT SELECT ON vehicle_years_exide TO {_PUBLIC_ROLE}")
    # Row data is NOT restored — re-run pipelines/exide_fitment_clean.py after
    # downgrading if the table needs to be repopulated.

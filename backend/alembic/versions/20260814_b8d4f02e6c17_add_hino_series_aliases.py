"""add Hino export-series -> JDM model aliases

Hino sells the same trucks under export "Series" names and JDM nameplates:
300 Series = Dutro, 500 Series = Ranger, 700 Series = Profia. Our CRSP-derived
vehicle_years rows use the JDM names while Exide's oem_fitment guide uses the
export names, so nothing linked ~1,100 Hino rows to the year data that exists
for them. model_aliases is the table this repo already uses for exactly this
international -> JDM resolution.

Also benefits live matching: a customer searching "Hino 300 Series" now
resolves to the Dutro rows.

Revision ID: b8d4f02e6c17
Revises: a7c3e91d5b42
Create Date: 2026-08-14
"""
from alembic import op
import sqlalchemy as sa

revision = 'b8d4f02e6c17'
down_revision = 'a7c3e91d5b42'
branch_labels = None
depends_on = None

# priority 999 matches the convention used by the existing non-ranked entries
# (see the CAMRY/LAND CRUISER rows seeded previously) — these are one-to-one
# mappings, not ranked alternatives, so no ordering is implied.
_ALIASES = [
    ("HINO", "300 SERIES", "DUTRO", 999),
    ("HINO", "500 SERIES", "RANGER", 999),
    ("HINO", "700 SERIES", "PROFIA", 999),
]


def upgrade() -> None:
    aliases = sa.table(
        "model_aliases",
        sa.column("make", sa.String),
        sa.column("international_model", sa.String),
        sa.column("jdm_model", sa.String),
        sa.column("priority", sa.Integer),
    )
    op.bulk_insert(aliases, [
        {"make": mk, "international_model": intl, "jdm_model": jdm, "priority": pr}
        for mk, intl, jdm, pr in _ALIASES
    ])


def downgrade() -> None:
    for mk, intl, jdm, _pr in _ALIASES:
        op.execute(
            sa.text(
                "DELETE FROM model_aliases WHERE make = :mk"
                " AND international_model = :intl AND jdm_model = :jdm"
            ).bindparams(mk=mk, intl=intl, jdm=jdm)
        )

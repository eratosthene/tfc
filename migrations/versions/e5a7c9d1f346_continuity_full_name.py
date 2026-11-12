"""Add continuity.full_name (additive only)

Continuity names come from the wiki page suffixes (G1, RID, ROTF), which are
abbreviations. full_name holds the spelled-out name for display.

Revision ID: e5a7c9d1f346
Revises: d4f6b8c0e235
Create Date: 2026-11-12 18:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e5a7c9d1f346"
down_revision = "d4f6b8c0e235"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "continuity", sa.Column("full_name", sa.String(length=255), nullable=True)
    )


def downgrade():
    op.drop_column("continuity", "full_name")

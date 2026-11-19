"""Add figure.af411_skipped (additive only)

Set from the ActionFigure411 queue for a figure that has no page on the site.

Revision ID: g7c9e1f3b568
Revises: f6b8d0e2a457
Create Date: 2026-11-18 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "g7c9e1f3b568"
down_revision = "f6b8d0e2a457"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "figure",
        sa.Column("af411_skipped", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_column("figure", "af411_skipped")

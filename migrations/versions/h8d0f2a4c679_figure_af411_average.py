"""Add figure.af411_average and figure.af411_average_on (additive only)

The recent sold average from the figure's ActionFigure411 My Collection row, and
the day it was copied over. Nothing keeps them up to date.

Revision ID: h8d0f2a4c679
Revises: g7c9e1f3b568
Create Date: 2026-11-18 18:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "h8d0f2a4c679"
down_revision = "g7c9e1f3b568"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "figure",
        sa.Column("af411_average", sa.Numeric(precision=10, scale=2), nullable=True),
    )
    op.add_column("figure", sa.Column("af411_average_on", sa.Date(), nullable=True))


def downgrade():
    op.drop_column("figure", "af411_average_on")
    op.drop_column("figure", "af411_average")

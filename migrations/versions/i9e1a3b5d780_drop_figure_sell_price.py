"""Drop figure.sell_price (destructive: the values in it are lost)

Never filled in: figures are removed from the collection when sold, and the
home page values figures by their ActionFigure411 average instead.

Revision ID: i9e1a3b5d780
Revises: h8d0f2a4c679
Create Date: 2026-11-26 18:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "i9e1a3b5d780"
down_revision = "h8d0f2a4c679"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("figure", "sell_price")


def downgrade():
    op.add_column(
        "figure",
        sa.Column("sell_price", sa.Numeric(precision=10, scale=2), nullable=True),
    )

"""Add figure.sell_price and figure.af411_link (additive only)

Both are typed in by the user: a price after looking at sold listings, and the
figure's page on actionfigure411.com once it is found. Nothing fills them in.

Revision ID: f6b8d0e2a457
Revises: e5a7c9d1f346
Create Date: 2026-11-18 09:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f6b8d0e2a457"
down_revision = "e5a7c9d1f346"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "figure",
        sa.Column("sell_price", sa.Numeric(precision=10, scale=2), nullable=True),
    )
    op.add_column(
        "figure", sa.Column("af411_link", sa.String(length=500), nullable=True)
    )


def downgrade():
    op.drop_column("figure", "af411_link")
    op.drop_column("figure", "sell_price")

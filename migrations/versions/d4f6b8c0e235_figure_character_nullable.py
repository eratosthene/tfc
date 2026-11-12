"""Let figure.character_id (the old character link) be empty

The cutover app writes figure.character_id_new, so a figure it creates has no
old character. Dropping NOT NULL loses nothing and is safe on every deploy; the
contract revision removes the column later.

Revision ID: d4f6b8c0e235
Revises: c3e5a7b9d124
Create Date: 2026-11-12 16:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d4f6b8c0e235"
down_revision = "c3e5a7b9d124"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("figure", "character_id", existing_type=sa.Integer(), nullable=True)


def downgrade():
    # Only possible while every figure still has an old character.
    op.alter_column(
        "figure", "character_id", existing_type=sa.Integer(), nullable=False
    )

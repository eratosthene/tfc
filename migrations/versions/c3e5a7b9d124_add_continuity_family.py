"""Add continuity_family and continuity.family_id (additive only)

A family groups continuities the way the wiki does (Aligned, Generation 1,
Robots in Disguise), so figures can later be filtered by it. Nothing fills it
yet; see docs/proposals/data-model.md.

Revision ID: c3e5a7b9d124
Revises: b2d4f6a8c013
Create Date: 2026-11-12 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c3e5a7b9d124"
down_revision = "b2d4f6a8c013"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "continuity_family",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("link", sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.add_column("continuity", sa.Column("family_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_continuity_family_id",
        "continuity",
        "continuity_family",
        ["family_id"],
        ["id"],
    )


def downgrade():
    op.drop_constraint("fk_continuity_family_id", "continuity", type_="foreignkey")
    op.drop_column("continuity", "family_id")
    op.drop_table("continuity_family")

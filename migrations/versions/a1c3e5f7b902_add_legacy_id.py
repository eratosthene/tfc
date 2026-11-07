"""Add legacy_id, the MongoDB ObjectId a row was migrated from

Revision ID: a1c3e5f7b902
Revises: efa4dd55219d
Create Date: 2026-11-06 19:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a1c3e5f7b902"
down_revision = "efa4dd55219d"
branch_labels = None
depends_on = None

TABLES = (
    "accessory",
    "category",
    "faction",
    "figure",
    "franchise",
    "tf_wiki_link",
    "tooling",
)


def upgrade():
    for table in TABLES:
        op.add_column(
            table, sa.Column("legacy_id", sa.String(length=24), nullable=True)
        )
        op.create_unique_constraint(None, table, ["legacy_id"])


def downgrade():
    for table in TABLES:
        # The unique index is named after its column on MariaDB.
        op.drop_constraint("legacy_id", table, type_="unique")
        op.drop_column(table, "legacy_id")

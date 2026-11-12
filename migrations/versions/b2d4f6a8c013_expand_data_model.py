"""Expand the schema for the new data model (additive only)

Adds the continuity, character, figure_reference, franchise_alias and
data_model_migration tables, and the franchise.parent_id, figure.link,
figure.character_id_new and figure.accessories_text columns. Nothing is
dropped or changed, so it is safe to apply on every deploy
(docker/docker-entrypoint.sh runs ``flask db upgrade``). The data is copied
afterwards, by hand, with scripts/migrate_data_model.py.

See docs/proposals/data-model.md, section 4.

Revision ID: b2d4f6a8c013
Revises: a1c3e5f7b902
Create Date: 2026-11-12 10:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b2d4f6a8c013"
down_revision = "a1c3e5f7b902"
branch_labels = None
depends_on = None

TABLE_ARGS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}


def upgrade():
    op.create_table(
        "continuity",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("link", sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        **TABLE_ARGS,
    )
    op.create_table(
        "character",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("link", sa.String(length=500), nullable=False),
        sa.Column("continuity_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["continuity_id"], ["continuity.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("link"),
        **TABLE_ARGS,
    )
    op.create_table(
        "franchise_alias",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("franchise_id", sa.Integer(), nullable=False),
        sa.Column("alias", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(["franchise_id"], ["franchise.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("alias"),
        **TABLE_ARGS,
    )
    op.create_table(
        "figure_reference",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("figure_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("link", sa.String(length=500), nullable=False),
        sa.ForeignKeyConstraint(["figure_id"], ["figure.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        **TABLE_ARGS,
    )
    op.create_table(
        "data_model_migration",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("step", sa.String(length=60), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("step"),
        **TABLE_ARGS,
    )

    op.add_column("franchise", sa.Column("parent_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_franchise_parent_id", "franchise", "franchise", ["parent_id"], ["id"]
    )
    op.add_column("figure", sa.Column("link", sa.String(length=500), nullable=True))
    op.add_column("figure", sa.Column("character_id_new", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_figure_character_id_new",
        "figure",
        "character",
        ["character_id_new"],
        ["id"],
    )
    op.add_column("figure", sa.Column("accessories_text", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("figure", "accessories_text")
    op.drop_constraint("fk_figure_character_id_new", "figure", type_="foreignkey")
    op.drop_column("figure", "character_id_new")
    op.drop_column("figure", "link")
    op.drop_constraint("fk_franchise_parent_id", "franchise", type_="foreignkey")
    op.drop_column("franchise", "parent_id")
    op.drop_table("data_model_migration")
    op.drop_table("figure_reference")
    op.drop_table("franchise_alias")
    op.drop_table("character")
    op.drop_table("continuity")

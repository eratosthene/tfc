"""Contract: drop the old structures the new data model replaced

THIS DROPS DATA. Take a backup (scripts/backup.sh) first; after this revision
the only way back to the old tables is a restore.

It removes ``tf_wiki_link``, ``accessory``, ``figure_accessory``,
``figure_history``, ``figure_packed_with``, ``figure.figure_link_id`` and the old
``figure.character_id``, then gives the new columns their final names
(``character_id_new`` -> ``character_id``, ``accessories_text`` ->
``accessories``) and makes ``character_id`` NOT NULL.

If the database holds any figures, links or accessories it refuses to run
unless the data migration's ``verify`` step is recorded in
``data_model_migration`` (that is, the new structures were checked against the
old ones once), and it always refuses while a figure has no character. A new,
empty database has nothing to lose and upgrades straight through.

Because the container runs ``flask db upgrade`` on start, deploying an image
that contains this revision applies it. Do not deploy it until you mean to.

The downgrade recreates the empty *structure* only; the data comes back from a
backup.

See docs/proposals/data-model.md, section 4.

Revision ID: j0f2b4c6e891
Revises: i9e1a3b5d780
Create Date: 2026-11-15 10:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "j0f2b4c6e891"
down_revision = "i9e1a3b5d780"
branch_labels = None
depends_on = None

TABLE_ARGS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}


def _refuse(why):
    raise RuntimeError(
        "Refusing to drop the old data model: %s. Nothing was changed. See the "
        "README, 'Dropping the old tables'." % why
    )


def _count(bind, table):
    return bind.execute(sa.text("SELECT COUNT(*) FROM `%s`" % table)).scalar()


def _guard(bind):
    has_data = any(_count(bind, t) for t in ("figure", "tf_wiki_link", "accessory"))
    verified = bind.execute(
        sa.text("SELECT COUNT(*) FROM data_model_migration WHERE step = 'verify'")
    ).scalar()
    if has_data and not verified:
        _refuse(
            "the data migration's verify step is not recorded in "
            "data_model_migration, so the new structures were never checked "
            "against the old ones"
        )
    missing = bind.execute(
        sa.text("SELECT COUNT(*) FROM figure WHERE character_id_new IS NULL")
    ).scalar()
    if missing:
        _refuse("%d figure(s) have no character (figure.character_id_new)" % missing)


def _drop_foreign_keys(bind, table, column):
    """Drop every foreign key on ``table.column``, whatever it is named."""
    for fk in sa.inspect(bind).get_foreign_keys(table):
        if column in fk["constrained_columns"]:
            op.drop_constraint(fk["name"], table, type_="foreignkey")


def upgrade():
    bind = op.get_bind()
    _guard(bind)

    op.drop_table("figure_accessory")
    op.drop_table("figure_history")
    op.drop_table("figure_packed_with")

    for column in ("figure_link_id", "character_id"):
        _drop_foreign_keys(bind, "figure", column)
        op.drop_column("figure", column)
    op.drop_table("accessory")
    op.drop_table("tf_wiki_link")

    op.drop_constraint("fk_figure_character_id_new", "figure", type_="foreignkey")
    op.alter_column(
        "figure",
        "character_id_new",
        new_column_name="character_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_figure_character_id", "figure", "character", ["character_id"], ["id"]
    )
    op.alter_column(
        "figure",
        "accessories_text",
        new_column_name="accessories",
        existing_type=sa.Text(),
        existing_nullable=True,
    )


def _position_table(name, right, right_table):
    op.create_table(
        name,
        sa.Column("figure_id", sa.Integer(), nullable=False),
        sa.Column(right, sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["figure_id"], ["figure.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint([right], [right_table + ".id"]),
        sa.PrimaryKeyConstraint("figure_id", right),
        **TABLE_ARGS,
    )


def downgrade():
    """The old structure, empty. Restore a backup to get the data back."""
    op.alter_column(
        "figure",
        "accessories",
        new_column_name="accessories_text",
        existing_type=sa.Text(),
        existing_nullable=True,
    )
    op.drop_constraint("fk_figure_character_id", "figure", type_="foreignkey")
    op.alter_column(
        "figure",
        "character_id",
        new_column_name="character_id_new",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.create_foreign_key(
        "fk_figure_character_id_new",
        "figure",
        "character",
        ["character_id_new"],
        ["id"],
    )

    op.create_table(
        "tf_wiki_link",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("link", sa.String(length=500), nullable=False),
        sa.Column("legacy_id", sa.String(length=24), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("legacy_id"),
        **TABLE_ARGS,
    )
    op.create_table(
        "accessory",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("legacy_id", sa.String(length=24), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("legacy_id"),
        **TABLE_ARGS,
    )
    op.add_column("figure", sa.Column("figure_link_id", sa.Integer(), nullable=True))
    op.add_column("figure", sa.Column("character_id", sa.Integer(), nullable=True))
    for column in ("figure_link_id", "character_id"):
        op.create_foreign_key(None, "figure", "tf_wiki_link", [column], ["id"])
    _position_table("figure_accessory", "accessory_id", "accessory")
    _position_table("figure_history", "tf_wiki_link_id", "tf_wiki_link")
    _position_table("figure_packed_with", "tf_wiki_link_id", "tf_wiki_link")

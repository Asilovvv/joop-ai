"""panel users: staff logins, who wrote a reply and who closed a request

Revision ID: 0020
Revises: 0019
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

S = sqlmodel.sql.sqltypes.AutoString

COLUMNS = {
    "message": [sa.Column("author", S(), nullable=False, server_default="")],
    "lead": [sa.Column("closed_by", S(), nullable=False, server_default="")],
}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table, columns in COLUMNS.items():
        existing = {c["name"] for c in inspector.get_columns(table)}
        for column in columns:
            if column.name not in existing:
                op.add_column(table, column)
    if "paneluser" not in set(inspector.get_table_names()):  # otherwise created by create_all() before migrations
        op.create_table(
            "paneluser",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("name", S(), nullable=False),
            sa.Column("login", S(), nullable=False),
            sa.Column("password_hash", S(), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("last_login_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["business_id"], ["business.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("business_id", "login"),
        )
        op.create_index("ix_paneluser_business_id", "paneluser", ["business_id"])


def downgrade() -> None:
    op.drop_table("paneluser")
    for table, columns in COLUMNS.items():
        with op.batch_alter_table(table) as batch:
            for column in columns:
                batch.drop_column(column.name)

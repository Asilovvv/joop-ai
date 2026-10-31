"""Altegio integration: location, optional own token, external ids

Revision ID: 0016
Revises: 0015
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

TEXT = sqlmodel.sql.sqltypes.AutoString

COLUMNS = {
    "business": [
        sa.Column("altegio_location_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("altegio_token", TEXT(), nullable=False, server_default=""),
        sa.Column("altegio_synced_at", sa.DateTime(), nullable=True),
        sa.Column("altegio_error", TEXT(), nullable=False, server_default=""),
    ],
    "service": [sa.Column("external_id", TEXT(), nullable=False, server_default="")],
    "staff": [sa.Column("external_id", TEXT(), nullable=False, server_default="")],
    "booking": [sa.Column("external_id", TEXT(), nullable=False, server_default="")],
}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table, columns in COLUMNS.items():
        existing = {c["name"] for c in inspector.get_columns(table)}
        for column in columns:
            if column.name not in existing:
                op.add_column(table, column)


def downgrade() -> None:
    for table, columns in COLUMNS.items():
        with op.batch_alter_table(table) as batch:
            for column in columns:
                batch.drop_column(column.name)

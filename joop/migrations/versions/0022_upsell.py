"""upsell: the add-on offered with a service, and the offer's state on a booking

Revision ID: 0022
Revises: 0021
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

S = sqlmodel.sql.sqltypes.AutoString

COLUMNS = {
    "service": [sa.Column("upsell_id", sa.Integer(), nullable=False, server_default="0")],
    "booking": [
        sa.Column("upsell_status", S(), nullable=False, server_default=""),
        sa.Column("upsell_service", S(), nullable=False, server_default=""),
        sa.Column("upsell_price", sa.Integer(), nullable=False, server_default="0"),
    ],
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

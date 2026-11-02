"""amoCRM / Kommo: the account, its token, and the deal id of each booking, request and order

Revision ID: 0021
Revises: 0020
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

S = sqlmodel.sql.sqltypes.AutoString

COLUMNS = {
    "business": [
        sa.Column("crm_domain", S(), nullable=False, server_default=""),
        sa.Column("crm_token", S(), nullable=False, server_default=""),
        sa.Column("crm_pipeline_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("crm_synced_at", sa.DateTime(), nullable=True),
        sa.Column("crm_error", S(), nullable=False, server_default=""),
    ],
    "booking": [sa.Column("crm_id", S(), nullable=False, server_default="")],
    "lead": [sa.Column("crm_id", S(), nullable=False, server_default="")],
    "order": [sa.Column("crm_id", S(), nullable=False, server_default="")],
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

"""deposits: prepayment settings of a business and the prepayment state of a booking

Revision ID: 0018
Revises: 0017
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

TEXT = sqlmodel.sql.sqltypes.AutoString

COLUMNS = {
    "business": [
        sa.Column("deposit_amount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deposit_details", TEXT(), nullable=False, server_default=""),
        sa.Column("deposit_hours", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("deposit_auto_cancel", sa.Boolean(), nullable=False, server_default=sa.false()),
    ],
    "booking": [
        sa.Column("deposit_due", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deposit_status", TEXT(), nullable=False, server_default=""),
        sa.Column("deposit_deadline", sa.DateTime(), nullable=True),
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

"""questions before a visit and a reward for every N-th visit

Revision ID: 0012
Revises: 0011
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

S = sqlmodel.sql.sqltypes.AutoString
COLUMNS = {
    "business": [
        sa.Column("intake_questions", S(), nullable=False, server_default=""),
        sa.Column("loyalty_every", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("loyalty_reward", S(), nullable=False, server_default=""),
    ],
    "booking": [
        sa.Column("intake_status", S(), nullable=False, server_default=""),
        sa.Column("intake_answers", S(), nullable=False, server_default=""),
        sa.Column("loyalty_visit", sa.Integer(), nullable=False, server_default="0"),
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

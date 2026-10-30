"""group classes: slots with several seats

Revision ID: 0008
Revises: 0007
"""

from alembic import op
import sqlalchemy as sa


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

COLUMNS = {
    "staff": [sa.Column("group_size", sa.Integer(), nullable=False, server_default="0")],
    "slot": [
        sa.Column("seats", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("taken", sa.Integer(), nullable=False, server_default="0"),
    ],
}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table, columns in COLUMNS.items():
        existing = {c["name"] for c in inspector.get_columns(table)}
        for column in columns:
            if column.name not in existing:
                op.add_column(table, column)
    # Slots booked before this migration hold one booking each.
    op.execute("UPDATE slot SET taken = 1 WHERE status = 'booked' AND id IN (SELECT slot_id FROM booking WHERE status = 'booked')")


def downgrade() -> None:
    for table, columns in COLUMNS.items():
        with op.batch_alter_table(table) as batch:
            for column in columns:
                batch.drop_column(column.name)

"""lead nudges: when staff are reminded about a request nobody answered

Revision ID: 0019
Revises: 0018
"""

from alembic import op
import sqlalchemy as sa


revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

COLUMNS = {
    "business": [sa.Column("lead_nudge_minutes", sa.Integer(), nullable=False, server_default="30")],
    "lead": [sa.Column("nudged_at", sa.DateTime(), nullable=True)],
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

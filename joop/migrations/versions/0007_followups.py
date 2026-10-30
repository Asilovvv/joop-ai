"""after-visit follow-ups: ratings, review link, invitations to come again

Revision ID: 0007
Revises: 0006
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

S = sqlmodel.sql.sqltypes.AutoString
COLUMNS = {
    "business": [
        sa.Column("review_requests", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("review_url", S(), nullable=False, server_default=""),
        sa.Column("return_invites", sa.Boolean(), nullable=False, server_default=sa.false()),
    ],
    "service": [sa.Column("repeat_days", sa.Integer(), nullable=False, server_default="0")],
    "booking": [
        sa.Column("review_status", S(), nullable=False, server_default=""),
        sa.Column("review_asked_at", sa.DateTime(), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("return_status", S(), nullable=False, server_default=""),
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

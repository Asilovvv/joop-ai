"""conversation reviewed_at: when a person first opened the dialogue in the panel

Revision ID: 0027
Revises: 0026
"""

from alembic import op
import sqlalchemy as sa


revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("conversation")}
    if "reviewed_at" not in columns:
        op.add_column("conversation", sa.Column("reviewed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("conversation") as batch:
        batch.drop_column("reviewed_at")

"""Conversation.staff_test: the owner or staff writing to their own bot

Revision ID: 0048
Revises: 0047
"""

from alembic import op
import sqlalchemy as sa


revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "staff_test" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("conversation")}:
        op.add_column("conversation", sa.Column("staff_test", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("conversation") as batch:
        batch.drop_column("staff_test")

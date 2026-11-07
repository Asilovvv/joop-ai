"""Conversation.blocked_at/blocked_by: the block list

Revision ID: 0047
Revises: 0046
"""

from alembic import op
import sqlalchemy as sa


revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("conversation")}
    if "blocked_at" not in have:
        op.add_column("conversation", sa.Column("blocked_at", sa.DateTime(), nullable=True))
    if "blocked_by" not in have:
        op.add_column("conversation", sa.Column("blocked_by", sa.String(), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("conversation") as batch:
        batch.drop_column("blocked_by")
        batch.drop_column("blocked_at")

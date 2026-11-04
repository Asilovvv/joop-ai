"""invitations into empty slots: Conversation.invited_at

Revision ID: 0031
Revises: 0030
"""

from alembic import op
import sqlalchemy as sa


revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "invited_at" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("conversation")}:
        op.add_column("conversation", sa.Column("invited_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("conversation") as batch:
        batch.drop_column("invited_at")

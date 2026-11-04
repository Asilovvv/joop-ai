"""follow-up to a customer who asked and went quiet: Conversation.followup_at, Business.nudge_unfinished

Revision ID: 0030
Revises: 0029
"""

from alembic import op
import sqlalchemy as sa


revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "followup_at" not in {c["name"] for c in sa.inspect(bind).get_columns("conversation")}:
        op.add_column("conversation", sa.Column("followup_at", sa.DateTime(), nullable=True))
    if "nudge_unfinished" not in {c["name"] for c in sa.inspect(bind).get_columns("business")}:
        op.add_column("business", sa.Column("nudge_unfinished", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("business") as batch:
        batch.drop_column("nudge_unfinished")
    with op.batch_alter_table("conversation") as batch:
        batch.drop_column("followup_at")

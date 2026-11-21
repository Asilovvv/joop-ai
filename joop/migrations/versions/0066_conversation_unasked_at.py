"""Conversation.unasked_at: when the business last wrote first with what the customer may refuse

A rating request, an invitation to come again or into a free slot, the one follow-up, «снова в наличии». A bare «стоп» as
the customer's next word unsubscribes them: before, that word counted only after a broadcast or a reminder to reorder.

Revision ID: 0066
Revises: 0065
"""

from alembic import op
import sqlalchemy as sa


revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "unasked_at" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("conversation")}:
        op.add_column("conversation", sa.Column("unasked_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("conversation") as batch:
        batch.drop_column("unasked_at")

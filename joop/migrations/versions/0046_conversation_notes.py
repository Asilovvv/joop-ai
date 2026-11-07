"""ConversationNote: staff-only notes in a dialogue

Revision ID: 0046
Revises: 0045
"""

from alembic import op
import sqlalchemy as sa


revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "conversationnote" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "conversationnote",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("business.id"), nullable=False),
            sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversation.id"), nullable=False),
            sa.Column("author", sa.String(), nullable=False, server_default=""),
            sa.Column("text", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_conversationnote_business_id", "conversationnote", ["business_id"])
        op.create_index("ix_conversationnote_conversation_id", "conversationnote", ["conversation_id"])


def downgrade() -> None:
    op.drop_table("conversationnote")

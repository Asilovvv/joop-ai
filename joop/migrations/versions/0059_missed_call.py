"""MissedCall: each missed call reported by the owner's phone or PBX (joop/missed_calls.py)

Revision ID: 0059
Revises: 0058
"""

from alembic import op
import sqlalchemy as sa


revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "missedcall" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "missedcall",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("business.id"), nullable=False),
        sa.Column("phone", sa.String(), nullable=False, server_default=""),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversation.id"), nullable=True),
        sa.Column("sent", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_missedcall_business_id", "missedcall", ["business_id"])
    op.create_index("ix_missedcall_created_at", "missedcall", ["created_at"])


def downgrade() -> None:
    op.drop_table("missedcall")

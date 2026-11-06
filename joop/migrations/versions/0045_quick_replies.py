"""QuickReply: ready answers staff send from a dialogue

Revision ID: 0045
Revises: 0044
"""

from alembic import op
import sqlalchemy as sa


revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "quickreply" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "quickreply",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("business.id"), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("text", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_quickreply_business_id", "quickreply", ["business_id"])


def downgrade() -> None:
    op.drop_table("quickreply")

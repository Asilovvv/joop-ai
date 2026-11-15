"""StockWatch: «напишем, когда появится» for sold-out items (joop/restock.py)

Revision ID: 0055
Revises: 0054
"""

from alembic import op
import sqlalchemy as sa


revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "stockwatch" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "stockwatch",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("business.id"), nullable=False),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversation.id"), nullable=False),
        sa.Column("service_id", sa.Integer(), sa.ForeignKey("service.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("notified_at", sa.DateTime(), nullable=True),
    )
    for col in ("business_id", "conversation_id", "service_id"):
        op.create_index(f"ix_stockwatch_{col}", "stockwatch", [col])


def downgrade() -> None:
    op.drop_table("stockwatch")

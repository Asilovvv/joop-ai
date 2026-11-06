"""Joop's own API key and webhooks: Business.api_key_hash/hint, webhook_*; WebhookDelivery

Revision ID: 0043
Revises: 0042
"""

from alembic import op
import sqlalchemy as sa


revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None

COLUMNS = [
    ("api_key_hash", sa.String()), ("api_key_hint", sa.String()), ("webhook_url", sa.String()),
    ("webhook_secret", sa.String()), ("webhook_error", sa.String()),
]


def upgrade() -> None:
    bind = op.get_bind()
    have = {c["name"] for c in sa.inspect(bind).get_columns("business")}
    for name, kind in COLUMNS:
        if name not in have:
            op.add_column("business", sa.Column(name, kind, nullable=False, server_default=""))
    if "webhook_since" not in have:
        op.add_column("business", sa.Column("webhook_since", sa.DateTime(), nullable=True))
    if "ix_business_api_key_hash" not in {i["name"] for i in sa.inspect(bind).get_indexes("business")}:
        op.create_index("ix_business_api_key_hash", "business", ["api_key_hash"])
    if "webhookdelivery" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "webhookdelivery",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("business.id"), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("object_id", sa.Integer(), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("delivered_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.String(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_webhookdelivery_business_id", "webhookdelivery", ["business_id"])
        op.create_index("ix_webhookdelivery_created_at", "webhookdelivery", ["created_at"])


def downgrade() -> None:
    op.drop_table("webhookdelivery")
    op.drop_index("ix_business_api_key_hash", table_name="business")
    with op.batch_alter_table("business") as batch:
        for name, _ in COLUMNS:
            batch.drop_column(name)
        batch.drop_column("webhook_since")

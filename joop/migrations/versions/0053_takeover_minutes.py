"""Business.takeover_minutes: how long the AI stays out of a chat after a staff reply (default 12 hours)

Revision ID: 0053
Revises: 0052
"""

from alembic import op
import sqlalchemy as sa


revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "takeover_minutes" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("business")}:
        op.add_column("business", sa.Column("takeover_minutes", sa.Integer(), nullable=False, server_default="720"))


def downgrade() -> None:
    with op.batch_alter_table("business") as batch:
        batch.drop_column("takeover_minutes")

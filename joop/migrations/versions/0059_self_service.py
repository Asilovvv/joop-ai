"""Business.self_service: the AI cancels and moves a customer's own booking on request

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
    if "self_service" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("business")}:
        op.add_column("business", sa.Column("self_service", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    with op.batch_alter_table("business") as batch:
        batch.drop_column("self_service")

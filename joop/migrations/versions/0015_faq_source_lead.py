"""The handoff a frequent question was written from

Revision ID: 0015
Revises: 0014
"""

from alembic import op
import sqlalchemy as sa


revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("faq")}
    if "source_lead_id" not in existing:
        op.add_column("faq", sa.Column("source_lead_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("faq") as batch:
        batch.drop_column("source_lead_id")

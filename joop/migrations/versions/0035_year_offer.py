"""Subscription.year_offered_at: when the founder sent the year offer (joop/annual.py)

Revision ID: 0035
Revises: 0034
"""

from alembic import op
import sqlalchemy as sa


revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "year_offered_at" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("subscription")}:
        op.add_column("subscription", sa.Column("year_offered_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("subscription") as batch:
        batch.drop_column("year_offered_at")

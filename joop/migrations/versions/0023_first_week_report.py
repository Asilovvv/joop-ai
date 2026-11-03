"""first week report: when the day-7 report went to the owner

Revision ID: 0023
Revises: 0022
"""

from alembic import op
import sqlalchemy as sa


revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("business")}
    if "first_week_report_at" not in columns:
        op.add_column("business", sa.Column("first_week_report_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("business") as batch:
        batch.drop_column("first_week_report_at")

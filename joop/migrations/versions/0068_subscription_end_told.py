"""Subscription.end_told: which warning about the end of the trial or paid period the owner already got

A trial ran out in silence: nothing told the owner, and three days later the AI stopped. The morning summary now says
it at each step (three days left, the last day, the waiting days, the stop), once per step and period.

Revision ID: 0068
Revises: 0067
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "0068"
down_revision = "0067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "end_told" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("subscription")}:
        op.add_column("subscription", sa.Column("end_told", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("subscription") as batch:
        batch.drop_column("end_told")

"""Staff.altegio_times_at: when this person's free times were last read from Altegio

One sync reads at most MAX_CALLS from Altegio (about 13 people). It now starts with those read longest ago, so a
large salon's last people get their times on the next sync instead of never.

Revision ID: 0065
Revises: 0064
"""

from alembic import op
import sqlalchemy as sa


revision = "0065"
down_revision = "0064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "altegio_times_at" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("staff")}:
        op.add_column("staff", sa.Column("altegio_times_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("staff") as batch:
        batch.drop_column("altegio_times_at")

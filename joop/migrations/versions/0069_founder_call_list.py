"""FounderCallList: the founder's «позвонить сегодня», one row a day

The first paying customers come from calls: trials ending soon, owners stuck in the setup, AIs stopped for want of a
payment. The list goes to the founder's Telegram every morning; the row is the lock that sends it once.

Revision ID: 0069
Revises: 0068
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "0069"
down_revision = "0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "foundercalllist" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "foundercalllist",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("text", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("sent", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_foundercalllist_day", "foundercalllist", ["day"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_foundercalllist_day", table_name="foundercalllist")
    op.drop_table("foundercalllist")

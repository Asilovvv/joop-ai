"""waitlist: customers waiting for a time to free up

Revision ID: 0009
Revises: 0008
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

S = sqlmodel.sql.sqltypes.AutoString


def upgrade() -> None:
    if "waitlistentry" in set(sa.inspect(op.get_bind()).get_table_names()):
        return  # created by create_all() before migrations
    op.create_table(
        "waitlistentry",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column("day", sa.Date(), nullable=True),
        sa.Column("service", S(), nullable=False),
        sa.Column("customer_name", S(), nullable=False),
        sa.Column("customer_phone", S(), nullable=False),
        sa.Column("channel", S(), nullable=False),
        sa.Column("chat_id", S(), nullable=False),
        sa.Column("status", S(), nullable=False),
        sa.Column("notified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["business.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["lead.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_waitlistentry_business_id", "waitlistentry", ["business_id"])
    op.create_index("ix_waitlistentry_created_at", "waitlistentry", ["created_at"])


def downgrade() -> None:
    op.drop_table("waitlistentry")

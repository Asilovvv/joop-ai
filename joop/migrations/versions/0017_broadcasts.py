"""broadcasts: messages to customer groups, their recipients, and the customer's opt-out

Revision ID: 0017
Revises: 0016
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

S = sqlmodel.sql.sqltypes.AutoString


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "broadcast_opt_out" not in {c["name"] for c in inspector.get_columns("conversation")}:
        op.add_column("conversation", sa.Column("broadcast_opt_out", sa.Boolean(), nullable=False, server_default=sa.false()))
    tables = set(inspector.get_table_names())
    if "broadcast" not in tables:  # otherwise created by create_all() before migrations
        op.create_table(
            "broadcast",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("text", S(), nullable=False),
            sa.Column("text_ky", S(), nullable=False),
            sa.Column("segment", S(), nullable=False),
            sa.Column("segment_arg", S(), nullable=False),
            sa.Column("status", S(), nullable=False),
            sa.Column("total", sa.Integer(), nullable=False),
            sa.Column("sent", sa.Integer(), nullable=False),
            sa.Column("skipped", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["business_id"], ["business.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_broadcast_business_id", "broadcast", ["business_id"])
    if "broadcastdelivery" not in tables:
        op.create_table(
            "broadcastdelivery",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("broadcast_id", sa.Integer(), nullable=False),
            sa.Column("conversation_id", sa.Integer(), nullable=False),
            sa.Column("status", S(), nullable=False),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["broadcast_id"], ["broadcast.id"]),
            sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("broadcast_id", "conversation_id"),
        )
        op.create_index("ix_broadcastdelivery_broadcast_id", "broadcastdelivery", ["broadcast_id"])
        op.create_index("ix_broadcastdelivery_conversation_id", "broadcastdelivery", ["conversation_id"])


def downgrade() -> None:
    op.drop_table("broadcastdelivery")
    op.drop_table("broadcast")
    with op.batch_alter_table("conversation") as batch:
        batch.drop_column("broadcast_opt_out")

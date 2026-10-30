"""hotel stays and room nights

Revision ID: 0013
Revises: 0012
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

S = sqlmodel.sql.sqltypes.AutoString


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "stay" not in tables:
        op.create_table(
            "stay",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("staff_id", sa.Integer(), nullable=False),
            sa.Column("room_name", S(), nullable=False),
            sa.Column("check_in", sa.Date(), nullable=False),
            sa.Column("check_out", sa.Date(), nullable=False),
            sa.Column("guests", sa.Integer(), nullable=False),
            sa.Column("customer_name", S(), nullable=False),
            sa.Column("customer_phone", S(), nullable=False),
            sa.Column("conversation_id", sa.Integer(), nullable=True),
            sa.Column("channel", S(), nullable=False),
            sa.Column("chat_id", S(), nullable=False),
            sa.Column("status", S(), nullable=False),
            sa.Column("source", S(), nullable=False),
            sa.Column("created_off_hours", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["business_id"], ["business.id"]),
            sa.ForeignKeyConstraint(["staff_id"], ["staff.id"]),
            sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_stay_business_id", "stay", ["business_id"])
        op.create_index("ix_stay_staff_id", "stay", ["staff_id"])
        op.create_index("ix_stay_check_in", "stay", ["check_in"])
    if "roomnight" not in tables:
        op.create_table(
            "roomnight",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("staff_id", sa.Integer(), nullable=False),
            sa.Column("stay_id", sa.Integer(), nullable=False),
            sa.Column("night", sa.Date(), nullable=False),
            sa.Column("unit", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["business_id"], ["business.id"]),
            sa.ForeignKeyConstraint(["staff_id"], ["staff.id"]),
            sa.ForeignKeyConstraint(["stay_id"], ["stay.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("staff_id", "night", "unit"),
        )
        op.create_index("ix_roomnight_business_id", "roomnight", ["business_id"])
        op.create_index("ix_roomnight_staff_id", "roomnight", ["staff_id"])
        op.create_index("ix_roomnight_stay_id", "roomnight", ["stay_id"])
        op.create_index("ix_roomnight_night", "roomnight", ["night"])


def downgrade() -> None:
    op.drop_table("roomnight")
    op.drop_table("stay")

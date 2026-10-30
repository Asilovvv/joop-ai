"""jobs: items left for work and their status

Revision ID: 0011
Revises: 0010
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

S = sqlmodel.sql.sqltypes.AutoString


def upgrade() -> None:
    if "job" in set(sa.inspect(op.get_bind()).get_table_names()):
        return  # created by create_all() before migrations
    op.create_table(
        "job",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("number", S(), nullable=False),
        sa.Column("customer_name", S(), nullable=False),
        sa.Column("customer_phone", S(), nullable=False),
        sa.Column("phone_key", S(), nullable=False),
        sa.Column("item", S(), nullable=False),
        sa.Column("status", S(), nullable=False),
        sa.Column("price", S(), nullable=False),
        sa.Column("ready_by", sa.Date(), nullable=True),
        sa.Column("note", S(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("ready_notified", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["business.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_business_id", "job", ["business_id"])
    op.create_index("ix_job_number", "job", ["number"])
    op.create_index("ix_job_phone_key", "job", ["phone_key"])


def downgrade() -> None:
    op.drop_table("job")

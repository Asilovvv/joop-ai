"""placement tests for training centres

Revision ID: 0005
Revises: 0004
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

S = sqlmodel.sql.sqltypes.AutoString


def upgrade() -> None:
    if "placementtest" in set(sa.inspect(op.get_bind()).get_table_names()):
        return  # created by create_all() before migrations
    op.create_table(
        "placementtest",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("code", S(), nullable=False),
        sa.Column("title", S(), nullable=False),
        sa.Column("scale_text", S(), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["business.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_placementtest_business_id", "placementtest", ["business_id"])
    op.create_index("ix_placementtest_code", "placementtest", ["code"], unique=True)
    op.create_table(
        "placementquestion",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("test_id", sa.Integer(), nullable=False),
        sa.Column("section", S(), nullable=False),
        sa.Column("text", S(), nullable=False),
        sa.Column("options_json", S(), nullable=False),
        sa.Column("correct", sa.Integer(), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["business.id"]),
        sa.ForeignKeyConstraint(["test_id"], ["placementtest.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_placementquestion_business_id", "placementquestion", ["business_id"])
    op.create_index("ix_placementquestion_test_id", "placementquestion", ["test_id"])
    op.create_table(
        "placementattempt",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("test_id", sa.Integer(), nullable=False),
        sa.Column("token", S(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("status", S(), nullable=False),
        sa.Column("name", S(), nullable=False),
        sa.Column("phone", S(), nullable=False),
        sa.Column("consent", sa.Boolean(), nullable=False),
        sa.Column("answers_json", S(), nullable=False),
        sa.Column("sections_json", S(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("max_score", sa.Integer(), nullable=False),
        sa.Column("level", S(), nullable=False),
        sa.Column("late", sa.Boolean(), nullable=False),
        sa.Column("result_sent", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["business.id"]),
        sa.ForeignKeyConstraint(["test_id"], ["placementtest.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_placementattempt_business_id", "placementattempt", ["business_id"])
    op.create_index("ix_placementattempt_test_id", "placementattempt", ["test_id"])
    op.create_index("ix_placementattempt_token", "placementattempt", ["token"], unique=True)
    op.create_index("ix_placementattempt_conversation_id", "placementattempt", ["conversation_id"])


def downgrade() -> None:
    op.drop_table("placementattempt")
    op.drop_table("placementquestion")
    op.drop_table("placementtest")

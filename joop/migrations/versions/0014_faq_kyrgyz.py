"""Kyrgyz wording of a frequent question

Revision ID: 0014
Revises: 0013
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("faq")}
    if "question_ky" not in existing:
        op.add_column("faq", sa.Column("question_ky", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("faq") as batch:
        batch.drop_column("question_ky")

"""Lead.stage: the sales funnel stage moved by the AI (joop/funnel.py)

Revision ID: 0038
Revises: 0037
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "stage" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("lead")}:
        op.add_column("lead", sa.Column("stage", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="new"))


def downgrade() -> None:
    with op.batch_alter_table("lead") as batch:
        batch.drop_column("stage")

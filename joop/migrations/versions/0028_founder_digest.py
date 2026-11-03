"""founder digest: the founder's one line a week, kept as a journal

Revision ID: 0028
Revises: 0027
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "founderdigest" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "founderdigest",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("text", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("sent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_founderdigest_week_start", "founderdigest", ["week_start"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_founderdigest_week_start", table_name="founderdigest")
    op.drop_table("founderdigest")

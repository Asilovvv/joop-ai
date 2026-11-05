"""Instagram comments answered in Direct: Business.ig_comments, ig_comment_keywords, ig_comment_public_reply

Revision ID: 0033
Revises: 0032
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("business")}
    if "ig_comments" not in columns:
        op.add_column("business", sa.Column("ig_comments", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "ig_comment_keywords" not in columns:
        op.add_column("business", sa.Column("ig_comment_keywords", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=""))
    if "ig_comment_public_reply" not in columns:
        op.add_column("business", sa.Column("ig_comment_public_reply", sqlmodel.sql.sqltypes.AutoString(), nullable=False,
                                            server_default="Ответили вам в Директ"))


def downgrade() -> None:
    with op.batch_alter_table("business") as batch:
        batch.drop_column("ig_comment_public_reply")
        batch.drop_column("ig_comment_keywords")
        batch.drop_column("ig_comments")

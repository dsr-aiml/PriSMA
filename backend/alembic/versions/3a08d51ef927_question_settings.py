"""Retain each research question's chosen engine and model settings."""

from alembic import op
import sqlalchemy as sa

revision = "3a08d51ef927"
down_revision = "2b74c193ad06"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("report_questions", sa.Column("processing_options", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("report_questions", "processing_options")

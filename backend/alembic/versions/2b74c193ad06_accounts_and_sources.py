"""Usernames, immutable source passages, inference cache, and saved questions."""

import sqlalchemy as sa

from alembic import op

revision = "2b74c193ad06"
down_revision = "1f9ea52e9d4b"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("username", sa.String(32), nullable=True))
    connection = op.get_bind()
    users = sa.table("users", sa.column("id", sa.String), sa.column("username", sa.String))
    used = set()
    for user_id in connection.execute(sa.select(users.c.id).order_by(users.c.id)).scalars():
        base = "user_" + str(user_id).replace("-", "").lower()[:20]
        candidate, suffix = base, 1
        while candidate in used:
            candidate = base + "_" + str(suffix)
            suffix += 1
        used.add(candidate)
        connection.execute(users.update().where(users.c.id == user_id).values(username=candidate))
    with op.batch_alter_table("users") as batch:
        batch.alter_column("username", existing_type=sa.String(32), nullable=False)
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.add_column("investigations", sa.Column("processing_options", sa.JSON(), nullable=True))
    op.add_column("evidence", sa.Column("original_content", sa.Text(), nullable=True))
    op.create_table(
        "source_chunks",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column(
            "investigation_id",
            sa.String(36),
            sa.ForeignKey("investigations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "evidence_id", sa.String(80), sa.ForeignKey("evidence.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("start", sa.Integer(), nullable=False),
        sa.Column("end", sa.Integer(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=True),
        sa.Column("embedding_model", sa.String(128), nullable=True),
    )
    op.create_index("ix_source_chunks_investigation_id", "source_chunks", ["investigation_id"])
    op.create_index("ix_source_chunks_evidence_id", "source_chunks", ["evidence_id"])
    op.create_table(
        "model_cache",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_model_cache_user_id", "model_cache", ["user_id"])
    op.create_table(
        "report_questions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "investigation_id",
            sa.String(36),
            sa.ForeignKey("investigations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("answer", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_report_questions_investigation_id", "report_questions", ["investigation_id"])


def downgrade():
    op.drop_table("report_questions")
    op.drop_table("model_cache")
    op.drop_table("source_chunks")
    op.drop_column("evidence", "original_content")
    op.drop_column("investigations", "processing_options")
    op.drop_index("ix_users_username", table_name="users")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("username")

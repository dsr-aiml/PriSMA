"""Report-scoped conversations; preserve existing research as individual chats."""
from alembic import op
import sqlalchemy as sa
import uuid

revision = "4c17a862be39"
down_revision = "3a08d51ef927"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("research_chats",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("investigation_id", sa.String(36), sa.ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_research_chats_investigation_id", "research_chats", ["investigation_id"])
    with op.batch_alter_table("report_questions") as batch:
        batch.add_column(sa.Column("chat_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_questions_chat", "research_chats", ["chat_id"], ["id"], ondelete="CASCADE")
        batch.create_index("ix_report_questions_chat_id", ["chat_id"])
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT q.id, q.investigation_id, q.question, q.created_at, q.updated_at FROM report_questions q JOIN investigations i ON i.id=q.investigation_id WHERE i.mode != 'demo'"))
    # Stream the legacy backfill; never create a conversation for a reference run.
    for row in rows.mappings():
        key = str(uuid.uuid4())
        connection.execute(sa.text("INSERT INTO research_chats (id,investigation_id,title,created_at,updated_at) VALUES (:id,:report,:title,:created,:updated)"),
            {"id":key, "report":row["investigation_id"], "title":row["question"][:120], "created":row["created_at"], "updated":row["updated_at"]})
        connection.execute(sa.text("UPDATE report_questions SET chat_id=:chat WHERE id=:id"), {"chat":key,"id":row["id"]})


def downgrade():
    with op.batch_alter_table("report_questions") as batch:
        batch.drop_index("ix_report_questions_chat_id")
        batch.drop_constraint("fk_questions_chat", type_="foreignkey")
        batch.drop_column("chat_id")
    op.drop_table("research_chats")

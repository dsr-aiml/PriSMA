import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def uid():
    return str(uuid.uuid4())


def now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Investigation(Base):
    __tablename__ = "investigations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    domain: Mapped[str] = mapped_column(String(253))
    mode: Mapped[str] = mapped_column(String(16), default="demo")
    depth: Mapped[str] = mapped_column(String(16), default="standard")
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    report: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    processing_options: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), index=True
    )
    source_url: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(32))
    category: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    original_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    signals: Mapped[dict] = mapped_column(JSON)
    provenance: Mapped[str] = mapped_column(Text)
    collection_method: Mapped[str] = mapped_column(String(32))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), index=True
    )
    message: Mapped[str] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Chunk(Base):
    __tablename__ = "source_chunks"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), index=True
    )
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id", ondelete="CASCADE"), index=True)
    content: Mapped[str] = mapped_column(Text)
    start: Mapped[int] = mapped_column(Integer)
    end: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)


class ModelCache(Base):
    __tablename__ = "model_cache"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ResearchChat(Base):
    __tablename__ = "research_chats"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Question(Base):
    __tablename__ = "report_questions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), index=True
    )
    question: Mapped[str] = mapped_column(Text)
    chat_id: Mapped[str | None] = mapped_column(ForeignKey("research_chats.id", ondelete="CASCADE"), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="queued")
    answer: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    processing_options: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

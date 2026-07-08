"""SQLAlchemy ORM models for the assistant bot."""

import enum
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Enum, Integer, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared declarative base for all models."""


# ── Enumerations ────────────────────────────────────────────────────────


class TaskStatus(enum.Enum):
    open = "open"
    done = "done"


class NoteKind(enum.Enum):
    note = "note"
    decision = "decision"


# ── Models ──────────────────────────────────────────────────────────────


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_by_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus), default=TaskStatus.open, nullable=False
    )
    done_by_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class MessageLog(Base):
    __tablename__ = "messages_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tg_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_name: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[NoteKind] = mapped_column(Enum(NoteKind), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

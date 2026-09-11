from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.vectorstore import EMBEDDING_DIM

SOURCE_TYPES = ("pdf", "docx", "text")


class SopDocument(Base):
    """Document metadata/versioning — what the SOP Library list/version UI
    reads. Chunk text + embeddings live in SopChunk below, not here.
    """

    __tablename__ = "sop_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    uploaded_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class SopChunk(Base):
    """A single embedded chunk, tenant_id-scoped like every other table —
    not a separate vector store. document_name/version are denormalized
    here (rather than joined from SopDocument) so citations and re-upload
    versioning don't need an extra join on every query.
    """

    __tablename__ = "sop_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("sop_documents.id", ondelete="CASCADE"), nullable=False, index=True)

    document_name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    section: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)


class SopQueryLog(Base):
    """One row per question asked (via the /query endpoint or the chatbot's
    sop_query tool). Feeds the SOP Library panel's "most-asked procedures"
    (BRD §4.4) — matched_document_name is null when nothing relevant was
    found, so those queries don't count toward any document's tally.
    """

    __tablename__ = "sop_query_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)

    question: Mapped[str] = mapped_column(Text, nullable=False)
    matched_document_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

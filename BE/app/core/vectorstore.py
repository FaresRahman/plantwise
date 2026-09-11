"""SOP RAG embeddings live directly in Postgres via pgvector — no separate
vector DB server to run or persist. `modules/sop/models.py` defines its own
chunk table using the `Vector` type re-exported here, with the same
`tenant_id` column every other table has — isolation and querying both
follow the usual convention instead of needing per-tenant collections.

Example for Dev A/B when building modules/sop/models.py:

    from pgvector.sqlalchemy import Vector
    from app.core.vectorstore import EMBEDDING_DIM

    class SopChunk(Base):
        __tablename__ = "sop_chunks"
        id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
        tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
        document_id: Mapped[int] = mapped_column(ForeignKey("sop_documents.id"), index=True)
        content: Mapped[str] = mapped_column(Text)
        embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))

Querying (nearest neighbours for a tenant, via pgvector's SQLAlchemy comparator):

    stmt = (
        select(SopChunk)
        .where(SopChunk.tenant_id == tenant_id)
        .order_by(SopChunk.embedding.cosine_distance(query_embedding))
        .limit(5)
    )
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# BAAI/bge-base-en-v1.5 (see core/llm.py — fastembed, open-source, local)
# produces 768-dim vectors. If EMBEDDING_MODEL ever changes to a
# different-dimension model, this constant (and any already-created
# `embedding` columns) need to change too.
EMBEDDING_DIM = 768


async def ensure_pgvector_extension(conn: AsyncConnection) -> None:
    """Called once from db.py:init_db, before create_all — the `vector`
    column type used by modules/sop/models.py requires the extension to
    already exist in the database. The pgvector/pgvector Docker image (see
    docker-compose.yml) ships the extension binary; this just activates it.
    """
    await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

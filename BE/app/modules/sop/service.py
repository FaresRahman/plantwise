import io
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import ModuleSummary
from app.core.llm import get_chat_llm, get_embeddings
from app.modules.sop.models import SopChunk, SopDocument, SopQueryLog
from app.modules.sop.schemas import SopCitation, SopQueryResponse

STORAGE_ROOT = Path(__file__).resolve().parents[3] / "storage" / "sop"

CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
N_RESULTS = 5
# pgvector's cosine_distance() ranges [0, 2] (0 = identical, 1 = orthogonal,
# 2 = opposite). A distance above this is treated as "not relevant enough to
# answer from" — never guess.
DISTANCE_THRESHOLD = 0.5

_MARKDOWN_HEADING_RE = re.compile(r"^\s*#{1,6}\s+\S.*$")
# Only single-level numbering ("5.", "6)") counts as a heading — "5.1", "4.2"
# etc. are sub-point sentences within their parent section, not new sections.
_NUMBERED_HEADING_RE = re.compile(r"^\s*\d+[.)]?\s+\S.{0,79}$")
_CAPS_HEADING_RE = re.compile(r"^\s*[A-Z][A-Z\s/&-]{4,79}\s*$")


def _is_heading(line: str) -> bool:
    """A line is a heading if it's a markdown heading, OR a short single-level
    numbered/ALL-CAPS title line (<=80 chars total). Two things matter here:
    the length cap (without it, a numbered *sentence* wrapped across lines,
    e.g. "4.2 Identify all energy sources for the equipment...", would
    misfire as a new section) and restricting numbering to a single level
    (without it, "5.1 Confirm all tools..." — a short complete sub-step
    sentence, not a title — would also incorrectly start a new section).
    """
    if not line.strip():
        return False
    return bool(_MARKDOWN_HEADING_RE.match(line) or _NUMBERED_HEADING_RE.match(line) or _CAPS_HEADING_RE.match(line))


class SopError(Exception):
    pass


def _extract_text(content: bytes, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if ext == "docx":
        from docx import Document

        doc = Document(io.BytesIO(content))
        return "\n".join(p.text for p in doc.paragraphs)
    return content.decode("utf-8", errors="ignore")


def _split_sections(text: str) -> list[tuple[str, str]]:
    """Split raw document text into (section_label, body) pairs using simple
    heading heuristics (markdown #, numbered headings, ALL-CAPS lines) — no
    ML, just explainable structure so citations point somewhere meaningful.
    """
    lines = text.splitlines()
    sections: list[tuple[str, list[str]]] = []
    current_label = "Document"
    current_body: list[str] = []

    for line in lines:
        if _is_heading(line):
            if current_body:
                sections.append((current_label, current_body))
            current_label = line.strip().lstrip("#").strip()
            current_body = []
        else:
            current_body.append(line)

    if current_body:
        sections.append((current_label, current_body))

    if not sections:
        sections = [("Document", lines)]

    return [(label, "\n".join(body).strip()) for label, body in sections if "\n".join(body).strip()]


def _chunk_text(text: str) -> list[str]:
    if len(text) <= CHUNK_SIZE:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - CHUNK_OVERLAP
    return chunks


def _chunk_document(text: str) -> list[tuple[str, str]]:
    """Returns list of (section_label, chunk_text)."""
    chunked: list[tuple[str, str]] = []
    for label, body in _split_sections(text):
        for chunk in _chunk_text(body):
            if chunk.strip():
                chunked.append((label, chunk))
    return chunked


async def fetch_url_content(url: str) -> tuple[bytes, str]:
    """BRD §4.4: document upload is 'PDF/DOCX; optional URL.' Fetches the
    resource so it flows through the exact same parse/chunk/embed pipeline
    as a direct file upload — a URL is just an alternate way to get bytes in,
    not a separate ingestion path.
    """
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            response = await client.get(url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SopError(f"Could not fetch document from URL: {exc}") from exc

    filename = Path(urlparse(url).path).name or "document"
    if "." not in filename:
        content_type = response.headers.get("content-type", "")
        if "pdf" in content_type:
            filename += ".pdf"
        elif "wordprocessingml" in content_type:
            filename += ".docx"
        else:
            filename += ".txt"
    return response.content, filename


async def upload_document(
    db: AsyncSession,
    tenant_id: int,
    user_id: int,
    filename: str,
    content: bytes,
    name: str | None,
    tags: list[str],
) -> SopDocument:
    doc_name = name or filename
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "text"
    source_type = ext if ext in ("pdf", "docx") else "text"

    text = _extract_text(content, filename)
    if not text.strip():
        raise SopError("Could not extract any text from this file")

    chunks = _chunk_document(text)
    if not chunks:
        raise SopError("Document produced no chunkable content")

    existing = await db.scalar(
        select(SopDocument).where(SopDocument.tenant_id == tenant_id, SopDocument.name == doc_name)
    )

    if existing:
        await db.execute(delete(SopChunk).where(SopChunk.document_id == existing.id))
        document = existing
        document.version += 1
        document.source_type = source_type
        document.tags = tags
        document.chunk_count = len(chunks)
        document.uploaded_by = user_id
        document.uploaded_at = datetime.now(timezone.utc).replace(tzinfo=None)
    else:
        document = SopDocument(
            tenant_id=tenant_id,
            name=doc_name,
            version=1,
            source_type=source_type,
            tags=tags,
            chunk_count=len(chunks),
            uploaded_by=user_id,
        )
        db.add(document)
        await db.flush()  # get document.id before writing the file / embedding

    # Embed before touching disk/DB rows so a failed embedding call (e.g. no
    # key, rate limit) leaves nothing to clean up — the SopDocument row also
    # rolls back automatically since it was only flushed, not committed.
    embeddings = get_embeddings().embed_documents([chunk for _, chunk in chunks])

    file_dir = STORAGE_ROOT / str(tenant_id)
    file_dir.mkdir(parents=True, exist_ok=True)
    file_path = file_dir / f"{document.id}_{filename}"
    file_path.write_bytes(content)
    document.file_path = str(file_path)

    for (label, chunk), embedding in zip(chunks, embeddings):
        db.add(
            SopChunk(
                tenant_id=tenant_id,
                document_id=document.id,
                document_name=doc_name,
                version=document.version,
                section=label,
                content=chunk,
                embedding=embedding,
            )
        )

    await db.commit()
    await db.refresh(document)
    return document


async def list_documents(db: AsyncSession, tenant_id: int) -> list[SopDocument]:
    result = await db.scalars(
        select(SopDocument).where(SopDocument.tenant_id == tenant_id).order_by(SopDocument.name)
    )
    return list(result)


async def delete_document(db: AsyncSession, tenant_id: int, document_id: int) -> None:
    document = await db.scalar(
        select(SopDocument).where(SopDocument.tenant_id == tenant_id, SopDocument.id == document_id)
    )
    if not document:
        raise SopError("Document not found")

    await db.execute(delete(SopChunk).where(SopChunk.document_id == document.id))

    if document.file_path and Path(document.file_path).exists():
        Path(document.file_path).unlink()

    await db.delete(document)
    await db.commit()


async def query_sop(db: AsyncSession, tenant_id: int, question: str) -> SopQueryResponse:
    query_embedding = get_embeddings().embed_query(question)

    distance = SopChunk.embedding.cosine_distance(query_embedding)
    stmt = (
        select(SopChunk, distance.label("distance"))
        .where(SopChunk.tenant_id == tenant_id)
        .order_by(distance)
        .limit(N_RESULTS)
    )
    rows = (await db.execute(stmt)).all()
    relevant = [(chunk, dist) for chunk, dist in rows if dist <= DISTANCE_THRESHOLD]

    if not relevant:
        db.add(SopQueryLog(tenant_id=tenant_id, question=question, matched_document_name=None))
        await db.commit()
        return SopQueryResponse(
            answer=(
                "I couldn't find anything in the SOP library relevant to that question. "
                "It may not be covered by an uploaded document yet. If you have access to the "
                "SOP Library, upload the relevant procedure there and ask again."
            ),
            citations=[],
            found=False,
        )

    context = "\n\n".join(
        f"[Document: {chunk.document_name} | Section: {chunk.section}]\n{chunk.content}" for chunk, _ in relevant
    )
    prompt = (
        "You are answering a manufacturing plant operator's question using ONLY the SOP excerpts "
        "below. Never invent information that isn't in the excerpts. If the excerpts don't fully "
        "answer the question, say what's missing. Cite the document and section you drew from.\n\n"
        f"SOP excerpts:\n{context}\n\nQuestion: {question}\n\nAnswer:"
    )
    llm = get_chat_llm(temperature=0)
    response = await llm.ainvoke(prompt)
    answer = response.content if isinstance(response.content, str) else str(response.content)

    citations = [
        SopCitation(document_name=chunk.document_name, section=chunk.section, snippet=chunk.content[:280])
        for chunk, _ in relevant
    ]
    db.add(SopQueryLog(tenant_id=tenant_id, question=question, matched_document_name=relevant[0][0].document_name))
    await db.commit()
    return SopQueryResponse(answer=answer, citations=citations, found=True)


async def sop_query_tool(db: AsyncSession, tenant_id: int, question: str) -> dict:
    result = await query_sop(db, tenant_id, question)
    return result.model_dump()


async def get_most_asked(db: AsyncSession, tenant_id: int, limit: int = 5) -> list[dict]:
    """BRD §4.4 SOP Library panel: 'documents indexed, last updated, and
    most-asked procedures.' Counts queries logged by query_sop that actually
    matched a document, grouped by that document, most-queried first.
    """
    rows = (
        await db.execute(
            select(SopQueryLog.matched_document_name, func.count().label("count"))
            .where(SopQueryLog.tenant_id == tenant_id, SopQueryLog.matched_document_name.is_not(None))
            .group_by(SopQueryLog.matched_document_name)
            .order_by(func.count().desc())
            .limit(limit)
        )
    ).all()
    return [{"document_name": name, "query_count": count} for name, count in rows]


async def get_summary(db: AsyncSession, tenant_id: int) -> ModuleSummary:
    count = await db.scalar(select(func.count()).select_from(SopDocument).where(SopDocument.tenant_id == tenant_id))
    latest = await db.scalar(
        select(func.max(SopDocument.uploaded_at)).where(SopDocument.tenant_id == tenant_id)
    )
    count = count or 0
    headline = f"{count} document{'s' if count != 1 else ''} indexed" if count else "No documents uploaded yet"
    return ModuleSummary(
        module="sop",
        title="SOP Library",
        status="ok",
        headline=headline,
        metrics=[{"label": "Documents", "value": str(count)}],
        last_updated_at=latest,
        is_stale=False,
        drilldown_path="/sop",
    )

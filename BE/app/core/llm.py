"""Single place the SOP/RAG pipeline and the chatbot get their model clients
from. Don't instantiate ChatOpenAI / the embedding model anywhere else — if
either ever changes, it should change once, here.

Chat uses OpenAI (we have a key, and it's the strongest option for the
agentic chatbot + recommendation reasoning). Embeddings deliberately do NOT
use OpenAI — SOP/quality-document RAG runs on an open-source, local model
via `fastembed` (ONNX runtime, no PyTorch/GPU required): no per-call API
cost, no external dependency for a core retrieval path, and no data leaving
the process for something as simple as a vector representation of a chunk
of text. Model weights download once (cached under `~/.cache/fastembed` /
`FASTEMBED_CACHE_PATH`) the first time `get_embeddings()` constructs the
model — see main.py's startup hook, which calls this eagerly so that cost
is paid once at boot, not on a user's first request.
"""
from functools import lru_cache

from fastembed import TextEmbedding
from langchain_core.embeddings import Embeddings
from langchain_openai import ChatOpenAI

from app.core.config import settings


def get_chat_llm(temperature: float = 0.2) -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.OPENAI_CHAT_MODEL,
        temperature=temperature,
        api_key=settings.OPENAI_API_KEY,
    )


class _FastEmbedEmbeddings(Embeddings):
    """Thin LangChain-compatible wrapper around fastembed's TextEmbedding so
    callers (SOP ingestion/query, any future RAG tool) use the same
    `embed_documents`/`embed_query` interface they'd use with any other
    LangChain embeddings backend — swapping the backend later doesn't touch
    call sites.
    """

    def __init__(self, model_name: str):
        self._model = TextEmbedding(model_name=model_name)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [vec.tolist() for vec in self._model.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return next(self._model.query_embed(text)).tolist()


_embedding_model: Embeddings | None = None


@lru_cache(maxsize=1)
def get_embeddings() -> Embeddings:
    """Open-source embedding model — see core/vectorstore.py:EMBEDDING_DIM
    for the corresponding vector column width; the two must be changed
    together. `lru_cache` ensures the (potentially slow, first-time:
    downloading) model construction happens once per process, not per call.
    """
    global _embedding_model
    _embedding_model = _FastEmbedEmbeddings(settings.EMBEDDING_MODEL)
    return _embedding_model

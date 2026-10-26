"""Builds the app's objects from settings. Shared by the API and the command-line scripts."""

from openai import OpenAI

from app.chat.llm import LLMClient
from app.chat.service import ChatService
from app.config import Settings
from app.retrieval.embeddings import Embedder
from app.retrieval.knowledge_base import KnowledgeBase
from app.storage import Storage


def openai_client(settings: Settings) -> OpenAI:
    if settings.openai_api_key is None:
        raise RuntimeError("OPENAI_API_KEY is not set. Copy .env.example to .env and add your key.")
    return OpenAI(api_key=settings.openai_api_key.get_secret_value(), timeout=30, max_retries=2)


def load_knowledge_base(settings: Settings, embedder: Embedder) -> KnowledgeBase:
    try:
        kb = KnowledgeBase.load(settings.index_dir, embedder.embed_query)
    except FileNotFoundError as exc:
        raise RuntimeError("No knowledge base index found. Run `python -m scripts.ingest` first.") from exc
    if kb.embedding_model != embedder.model:
        raise RuntimeError(
            f"The index was built with {kb.embedding_model!r} but EMBEDDING_MODEL is "
            f"{embedder.model!r}. Run `python -m scripts.ingest` to rebuild it."
        )
    return kb


def chat_service(settings: Settings, client: OpenAI, kb: KnowledgeBase,
                 storage: Storage | None) -> ChatService:
    return ChatService(
        LLMClient(client, settings.llm_model, settings.llm_reasoning_effort),
        kb,
        storage,
        top_k=settings.retrieval_top_k,
        min_relevance=settings.min_relevance,
        history_turns=settings.history_turns,
    )

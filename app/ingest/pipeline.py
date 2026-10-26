"""Ingestion pipeline: crawl -> extract -> chunk -> embed -> save the index.

The admin refresh endpoint and the scheduler.
A page that fails to download keeps its previous version, so a temporary outage
never wipes content out of the knowledge base. Only chunks whose text changed are
re-embedded.
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np

from app.config import Settings
from app.ingest.chunker import Chunk, chunk_pages
from app.ingest.crawler import PoliteCrawler
from app.ingest.extractor import ExtractedPage, extract_page
from app.retrieval.embeddings import Embedder
from app.retrieval.knowledge_base import load_index, save_index

log = logging.getLogger(__name__)


class IngestError(RuntimeError):
    pass


@dataclass
class IngestReport:
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    finished_at: str | None = None
    pages: dict[str, str] = field(default_factory=dict)  # page id -> outcome
    chunks: int = 0
    embedded: int = 0  # chunks that needed new embeddings
    error: str | None = None


def run_ingestion(
    settings: Settings, embedder: Embedder, crawler: PoliteCrawler | None = None
) -> IngestReport:
    report = IngestReport()
    crawler = crawler or PoliteCrawler(settings.crawler_user_agent, settings.crawl_min_delay_seconds)
    sources = settings.load_sources()
    previous = _load_pages(settings)

    pages: list[ExtractedPage] = []
    for source in sources:
        result = crawler.fetch(source.url)
        page, error = None, result.error
        if result.ok:
            try:
                page = extract_page(result.html, source)
            except Exception as exc:  # a layout change must not break the whole refresh
                log.exception("Extraction failed for %s", source.url)
                error = f"extraction failed: {exc}"
            if page is not None and not page.sections:
                page, error = None, "no content extracted (page layout changed?)"

        old = previous.get(source.id)
        if page is None:
            if old:
                pages.append(old)
                report.pages[source.id] = f"failed ({error}); kept previous version"
            else:
                report.pages[source.id] = f"failed ({error})"
            continue

        if old is None:
            report.pages[source.id] = "new"
        elif old.content_hash == page.content_hash and old.url == page.url:
            report.pages[source.id] = "unchanged"
        else:
            report.pages[source.id] = "changed"
        _save_page(settings, page, result.html)
        pages.append(page)

    if not pages:
        raise IngestError("No page could be fetched or loaded; the index was not changed.")
    _remove_stale_pages(settings, keep={p.id for p in pages})

    chunks = chunk_pages(pages)
    vectors, report.embedded = _embed_with_cache(settings, embedder, chunks)
    save_index(
        settings.index_dir,
        chunks,
        vectors,
        manifest={
            "embedding_model": embedder.model,
            "pages": {p.id: {"title": p.title, "url": p.url, "content_hash": p.content_hash}
                      for p in pages},
        },
    )
    report.chunks = len(chunks)
    report.finished_at = datetime.now(UTC).isoformat(timespec="seconds")
    log.info("Ingestion finished: %s", report)
    return report


def _embed_with_cache(settings: Settings, embedder: Embedder, chunks: list[Chunk]) -> tuple[np.ndarray, int]:
    """Reuse vectors from the current index for chunks whose text is unchanged."""
    cache: dict[str, np.ndarray] = {}
    try:
        old_chunks, old_vectors, manifest = load_index(settings.index_dir)
        if manifest.get("embedding_model") == embedder.model:
            cache = {_text_hash(c.search_text): v for c, v in zip(old_chunks, old_vectors)}
    except FileNotFoundError:
        pass

    missing = [c for c in chunks if _text_hash(c.search_text) not in cache]
    if missing:
        log.info("Embedding %d new or changed chunks", len(missing))
        for chunk, vector in zip(missing, embedder.embed([c.search_text for c in missing])):
            cache[_text_hash(chunk.search_text)] = vector
    return np.stack([cache[_text_hash(c.search_text)] for c in chunks]), len(missing)


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_pages(settings: Settings) -> dict[str, ExtractedPage]:
    pages = {}
    for path in settings.pages_dir.glob("*.json"):
        page = ExtractedPage.from_dict(json.loads(path.read_text(encoding="utf-8")))
        pages[page.id] = page
    return pages


def _save_page(settings: Settings, page: ExtractedPage, html: str | None) -> None:
    settings.pages_dir.mkdir(parents=True, exist_ok=True)
    (settings.pages_dir / f"{page.id}.json").write_text(
        json.dumps(page.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    # Human-readable copy, handy for reviewing extraction quality.
    (settings.pages_dir / f"{page.id}.md").write_text(page.to_markdown(), encoding="utf-8")
    if html is not None:
        settings.raw_dir.mkdir(parents=True, exist_ok=True)
        (settings.raw_dir / f"{page.id}.html").write_text(html, encoding="utf-8")


def _remove_stale_pages(settings: Settings, keep: set[str]) -> None:
    """Delete saved pages whose source was removed from config/sources.yaml."""
    for path in settings.pages_dir.glob("*.*"):
        if path.stem not in keep:
            log.info("Removing %s (no longer a source)", path.name)
            path.unlink()

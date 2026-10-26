"""Content refresh: re-run ingestion in the background and swap in the new index."""

import logging
import threading
from collections.abc import Callable
from dataclasses import asdict

from app.config import Settings
from app.ingest.pipeline import IngestReport, run_ingestion
from app.retrieval.embeddings import Embedder
from app.retrieval.knowledge_base import KnowledgeBase

log = logging.getLogger(__name__)


class RefreshManager:
    """Runs one refresh at a time; the chat keeps using the old index until the new one is ready."""

    def __init__(self, settings: Settings, embedder: Embedder,
                 on_new_knowledge_base: Callable[[KnowledgeBase], None]):
        self._settings = settings
        self._embedder = embedder
        self._on_new_knowledge_base = on_new_knowledge_base
        self._lock = threading.Lock()
        self.last_report: IngestReport | None = None

    @property
    def running(self) -> bool:
        return self._lock.locked()

    def start(self) -> bool:
        """Start a refresh in a background thread. Returns False if one is already running."""
        if not self._lock.acquire(blocking=False):
            return False
        threading.Thread(target=self._run, name="content-refresh", daemon=True).start()
        return True

    def status(self) -> dict:
        return {
            "running": self.running,
            "last_report": asdict(self.last_report) if self.last_report else None,
        }

    def _run(self) -> None:
        report = IngestReport()
        try:
            report = run_ingestion(self._settings, self._embedder)
            kb = KnowledgeBase.load(self._settings.index_dir, self._embedder.embed_query)
            self._on_new_knowledge_base(kb)
            log.info("Knowledge base refreshed: %d chunks", len(kb.chunks))
        except Exception as exc:
            log.exception("Content refresh failed")
            report.error = f"{type(exc).__name__}: {exc}"
        finally:
            self.last_report = report
            self._lock.release()

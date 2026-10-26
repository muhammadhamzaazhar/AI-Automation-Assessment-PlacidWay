"""Crawl the source pages and (re)build the knowledge base index.

Usage:  python -m scripts.ingest
"""

import json
import logging
import sys
from dataclasses import asdict

from app import factory
from app.config import get_settings
from app.ingest.pipeline import IngestError, run_ingestion
from app.retrieval.embeddings import Embedder


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    embedder = Embedder(factory.openai_client(settings), settings.embedding_model)
    try:
        report = run_ingestion(settings, embedder)
    except IngestError as exc:
        logging.error("%s", exc)
        return 1
    print(json.dumps(asdict(report), indent=2))
    return 0 if all(not status.startswith("failed") for status in report.pages.values()) else 2


if __name__ == "__main__":
    sys.exit(main())

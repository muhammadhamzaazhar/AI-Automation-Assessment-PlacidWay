"""Chat with the bot in the terminal (handy for quick checks without the web UI).

Usage:  python -m scripts.chat
"""

import logging

from app import factory
from app.chat.schemas import ChatTurn
from app.config import get_settings
from app.retrieval.embeddings import Embedder


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    settings = get_settings()
    client = factory.openai_client(settings)
    kb = factory.load_knowledge_base(settings, Embedder(client, settings.embedding_model))
    service = factory.chat_service(settings, client, kb, storage=None)

    history: list[ChatTurn] = []
    disclaimer_shown = False
    print("Ask a question (empty line to quit).")
    while message := input("\nYou: ").strip():
        reply = service.reply(message, history, disclaimer_shown)
        print(f"\nBot: {reply.answer}")
        for source in reply.sources:
            print(f"  Source: {source.title} - {source.url}")
        if reply.disclaimer:
            print(f"  Note: {reply.disclaimer}")
            disclaimer_shown = True
        if reply.show_quote_cta:
            print(f"  Free quote: {settings.quote_url}")
        history += [ChatTurn(role="user", content=message), ChatTurn(role="assistant", content=reply.answer)]


if __name__ == "__main__":
    main()

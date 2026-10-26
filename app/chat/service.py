"""The chat pipeline.

1. Analyse (LLM call 1): intent, a standalone English question (resolves follow-ups),
   the visitor's language, and whether a medical disclaimer is relevant.
2. Non-questions (booking, quote, medical advice, greeting, out of scope) get a fixed reply.
3. Retrieve: hybrid search; if nothing is relevant enough, say "I don't know".
4. Answer (LLM call 2) from the retrieved excerpts only, as structured output.
5. Verify in code (guardrails); a failed check turns into "I don't know", never a guess.
Unanswered questions are logged so content gaps can be found.
"""

import logging
import re
from dataclasses import dataclass, field

from app.chat import messages
from app.chat.guardrails import verify_answer
from app.chat.llm import LLMClient, LLMError
from app.chat.prompts import (
    ANALYZE_INSTRUCTIONS,
    ANSWER_INSTRUCTIONS,
    TRANSLATE_INSTRUCTIONS,
    build_analyze_prompt,
    build_answer_prompt,
)
from app.chat.schemas import ChatTurn, GroundedAnswer, QueryAnalysis
from app.ingest.chunker import Chunk
from app.retrieval.knowledge_base import KnowledgeBase
from app.storage import Storage

log = logging.getLogger(__name__)

QUOTE_INTENTS = {"booking", "quote_request", "medical_advice"}


@dataclass
class Source:
    title: str
    url: str


@dataclass
class ChatReply:
    answer: str
    sources: list[Source] = field(default_factory=list)
    intent: str = "question"
    answerable: bool = True
    show_quote_cta: bool = False
    disclaimer: str | None = None
    standalone_question: str | None = None  


class ChatService:
    def __init__(
        self,
        llm: LLMClient,
        kb: KnowledgeBase,
        storage: Storage | None = None,
        top_k: int = 10,
        min_relevance: float = 0.25,
        history_turns: int = 6,
    ):
        self.llm = llm
        self.kb = kb  # replaced in place when the content is refreshed
        self.storage = storage
        self.top_k = top_k
        self.min_relevance = min_relevance
        self.history_turns = history_turns
        self._translations: dict[tuple[str, str], str] = {}

    def reply(self, message: str, history: list[ChatTurn], disclaimer_shown: bool = False) -> ChatReply:
        try:
            analysis = self.llm.parse(
                ANALYZE_INSTRUCTIONS,
                build_analyze_prompt(message, history[-2 * self.history_turns :]),
                QueryAnalysis,
            )
        except LLMError:
            log.exception("Message analysis failed")
            return ChatReply(messages.UNAVAILABLE, intent="error", answerable=False, show_quote_cta=True)

        language = _language_code(analysis.language)
        log.info("intent=%s lang=%s question=%r", analysis.intent, language, analysis.standalone_question)

        if analysis.intent != "question":
            return ChatReply(
                self._localize(messages.CANNED_REPLIES[analysis.intent], language),
                intent=analysis.intent,
                answerable=analysis.intent != "out_of_scope",
                show_quote_cta=analysis.intent in QUOTE_INTENTS,
                standalone_question=analysis.standalone_question,
            )

        disclaimer = None
        if analysis.needs_medical_disclaimer and not disclaimer_shown:
            disclaimer = self._localize(messages.DISCLAIMER, language)

        kb = self.kb
        hits = kb.search(analysis.standalone_question, self.top_k, self.min_relevance)
        if not hits:
            return self._not_found(message, analysis, language, "no relevant content", disclaimer)
        chunks = [hit.chunk for hit in hits]

        try:
            answer = self.llm.parse(
                ANSWER_INSTRUCTIONS,
                build_answer_prompt(analysis.standalone_question, message, language, chunks),
                GroundedAnswer,
            )
        except LLMError:
            log.exception("Answer generation failed")
            return ChatReply(messages.UNAVAILABLE, intent="error", answerable=False, show_quote_cta=True)

        check = verify_answer(answer.answer, answer.cited_chunk_ids, chunks, message)
        if not check.ok:
            log.warning("Answer rejected (%s): %r", check.reason, answer.answer)
            return self._not_found(message, analysis, language, f"guardrail: {check.reason}", disclaimer)
        if answer.answerable and not check.citations:
            log.warning("Answer rejected (no valid citations): %r", answer.answer)
            return self._not_found(message, analysis, language, "guardrail: no citations", disclaimer)

        if not answer.answerable:
            self._log_unanswered(message, analysis, language, "not covered by the pages")
        return ChatReply(
            answer=check.text,
            sources=_sources(check.citations),
            answerable=answer.answerable,
            show_quote_cta=not answer.answerable,
            disclaimer=disclaimer,
            standalone_question=analysis.standalone_question,
        )

    def _not_found(self, message: str, analysis: QueryAnalysis, language: str, reason: str,
                   disclaimer: str | None) -> ChatReply:
        self._log_unanswered(message, analysis, language, reason)
        return ChatReply(
            self._localize(messages.NOT_FOUND, language),
            answerable=False,
            show_quote_cta=True,
            disclaimer=disclaimer,
            standalone_question=analysis.standalone_question,
        )

    def _log_unanswered(self, message: str, analysis: QueryAnalysis, language: str, reason: str) -> None:
        if self.storage is None:
            return
        try:
            self.storage.log_unanswered(message, analysis.standalone_question, language, reason)
        except Exception:  # logging a gap must never break the reply
            log.exception("Could not log unanswered question")

    def _localize(self, text: str, language: str) -> str:
        """Translate a fixed English reply, caching the result per language."""
        if language == "en":
            return text
        key = (text, language)
        if key not in self._translations:
            try:
                self._translations[key] = self.llm.complete(
                    TRANSLATE_INSTRUCTIONS.format(language=language), text
                )
            except LLMError:
                log.exception("Translation to %s failed; replying in English", language)
                return text
        return self._translations[key]


def _language_code(raw: str) -> str:
    """Primary ISO 639 code ("es-MX" -> "es"); anything unexpected falls back to English."""
    code = raw.strip().lower()
    return code.split("-")[0] if re.fullmatch(r"[a-z]{2,3}(-[a-z]{2,4})?", code) else "en"


def _sources(chunks: list[Chunk]) -> list[Source]:
    unique = {c.url: Source(c.page_title, c.url) for c in chunks}
    return list(unique.values())

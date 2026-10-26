"""Deterministic checks on a generated answer, run before it reaches the visitor.

The prompt asks the model to stay grounded; these checks enforce it in code:
- every number in the answer (prices above all) must appear in the retrieved excerpts;
- a figure the visitor supplied may only be repeated next to a figure from the pages,
  i.e. to correct it, never on its own ("Yes, it costs $50");
- citations must point at excerpts that were actually retrieved;
- URLs are stripped from the answer text; sources come from chunk metadata instead.
"""

import re
from dataclasses import dataclass, field

from app.ingest.chunker import Chunk

# Eastern Arabic and Persian digits, plus Arabic thousands/decimal separators.
_DIGIT_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٬٫", "01234567890123456789,.")
_NUMBER = re.compile(
    r"(?P<currency>[$€£]\s?)?"
    r"(?P<number>\d{1,3}(?:[,.  ]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
)
_URL = re.compile(r"\(?https?://\S+\)?")
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\(https?://[^)]+\)")


@dataclass
class Verification:
    ok: bool
    text: str  # answer text with URLs removed
    citations: list[Chunk] = field(default_factory=list)
    reason: str | None = None


def verify_answer(answer: str, cited_ids: list[str], retrieved: list[Chunk], user_message: str) -> Verification:
    text = _strip_urls(answer)
    by_id = {c.id: c for c in retrieved}
    citations = [by_id[i] for i in dict.fromkeys(cited_ids) if i in by_id]

    answer_numbers = extract_numbers(text, skip_small=True)
    cited_numbers = set().union(*(extract_numbers(c.search_text) for c in citations))
    unsupported = answer_numbers - cited_numbers

    # The model sometimes forgets to cite an excerpt it used: add any retrieved excerpt
    # that contains the missing figures instead of rejecting a correct answer.
    for chunk in retrieved:
        found = unsupported & extract_numbers(chunk.search_text)
        if found:
            if chunk not in citations:
                citations.append(chunk)
            unsupported -= found

    echoed = unsupported & extract_numbers(user_message)
    unsupported -= echoed
    if unsupported:
        return Verification(False, text, citations, f"numbers not in sources: {_fmt(unsupported)}")
    if echoed and not (answer_numbers - echoed):
        return Verification(
            False, text, citations,
            f"repeats the visitor's figure {_fmt(echoed)} without any figure from the pages",
        )
    return Verification(True, text, citations)


def extract_numbers(text: str, skip_small: bool = False) -> set[float]:
    """All numbers in the text as values, e.g. "$18,995", "18.995" and "١٨٬٩٩٥" -> 18995.0.

    With skip_small, bare single digits (list numbering, "3 weeks") are ignored; a
    single digit with a currency sign ("$5") is still checked.
    """
    values = set()
    for match in _NUMBER.finditer(text.translate(_DIGIT_MAP)):
        value = _to_value(match.group("number"))
        if skip_small and value < 10 and value == int(value) and not match.group("currency"):
            continue
        values.add(value)
    return values


def _to_value(token: str) -> float:
    grouped = re.fullmatch(r"(\d{1,3}(?:[,.  ]\d{3})+)([.,]\d{1,2})?", token)
    if grouped:  # thousands separators: "18,995", "18.995", "18 995.50"
        integer = re.sub(r"\D", "", grouped.group(1))
        decimals = (grouped.group(2) or "").replace(",", ".")
        return round(float(integer + decimals), 2)
    return round(float(token.replace(",", ".")), 2)


def _strip_urls(text: str) -> str:
    text = _MARKDOWN_LINK.sub(r"\1", text)
    text = _URL.sub("", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _fmt(values: set[float]) -> str:
    return ", ".join(f"{v:g}" for v in sorted(values))

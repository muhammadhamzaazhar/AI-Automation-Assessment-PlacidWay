"""Data shapes shared by the chat pipeline, including the LLM's structured outputs."""

from typing import Literal

from pydantic import BaseModel, Field

Intent = Literal["question", "booking", "quote_request", "medical_advice", "greeting", "out_of_scope"]


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class QueryAnalysis(BaseModel):
    """Output of the first LLM call: what the visitor wants, as a standalone question."""

    intent: Intent
    standalone_question: str = Field(
        description="The visitor's request as a self-contained English question."
    )
    language: str = Field(description="ISO 639-1 code of the latest message, e.g. en, es, ar.")
    needs_medical_disclaimer: bool


class GroundedAnswer(BaseModel):
    """Output of the second LLM call: an answer built only from the retrieved excerpts."""

    answerable: bool = Field(description="True only if the excerpts contain what was asked.")
    answer: str
    cited_chunk_ids: list[str] = Field(description="chunk_id of every excerpt the answer uses.")

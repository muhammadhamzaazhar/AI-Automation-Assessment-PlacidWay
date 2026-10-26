"""Thin wrapper around the OpenAI Responses API with structured (Pydantic) outputs."""

import logging
from typing import TypeVar

import openai
from openai import OpenAI
from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """The model call failed or returned unusable output; callers show a fallback reply."""


class LLMClient:
    def __init__(
        self,
        client: OpenAI,
        model: str,
        reasoning_effort: str = "low",
        max_output_tokens: int = 4000,  # includes reasoning tokens
    ):
        self._client = client
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.max_output_tokens = max_output_tokens

    def parse(self, instructions: str, prompt: str, schema: type[T]) -> T:
        """Call the model and return its output validated against `schema`."""
        try:
            response = self._client.responses.parse(
                model=self.model,
                instructions=instructions,
                input=prompt,
                text_format=schema,
                reasoning={"effort": self.reasoning_effort},
                max_output_tokens=self.max_output_tokens,
                store=False,  
            )
        except (openai.OpenAIError, ValidationError) as exc:
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc

        if response.output_parsed is None:
            raise LLMError(f"No structured output (status={response.status})")
        return response.output_parsed

    def complete(self, instructions: str, prompt: str) -> str:
        """Plain-text completion, used for short translations."""
        try:
            response = self._client.responses.create(
                model=self.model,
                instructions=instructions,
                input=prompt,
                reasoning={"effort": self.reasoning_effort},
                max_output_tokens=self.max_output_tokens,
                store=False,
            )
        except openai.OpenAIError as exc:
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc

        if not response.output_text.strip():
            raise LLMError(f"Empty output (status={response.status})")
        return response.output_text.strip()

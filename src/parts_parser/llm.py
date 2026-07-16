import json
from typing import Protocol

import openai

from parts_parser.config import Settings, load_settings


class LLMError(Exception):
    """An AI service error whose message can be shown to end users."""


class LLMClient(Protocol):
    def complete_json(self, *, system: str, user: str, max_output_tokens: int = 4096) -> dict:
        """Return a JSON object produced from the supplied prompts."""
        ...


class OpenAIClient:
    def __init__(self, api_key: str, model: str = "gpt-5-mini") -> None:
        self._client = openai.OpenAI(api_key=api_key)
        self._model = model

    def complete_json(self, *, system: str, user: str, max_output_tokens: int = 4096) -> dict:
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
                max_completion_tokens=max_output_tokens,
            )
        except openai.OpenAIError as error:
            raise LLMError(
                "Couldn't reach the AI service. Check your internet connection "
                "and API key in Settings."
            ) from error

        try:
            return json.loads(response.choices[0].message.content)
        except json.JSONDecodeError as error:
            raise LLMError(
                "The AI returned an unreadable response. Please try running again."
            ) from error


def get_client(settings: Settings | None = None) -> LLMClient:
    settings = settings or load_settings()
    if not settings.openai_api_key:
        raise LLMError("No API key is set. Open Settings and paste your OpenAI API key.")

    return OpenAIClient(api_key=settings.openai_api_key, model=settings.model)

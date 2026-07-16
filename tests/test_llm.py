from types import SimpleNamespace

import pytest

from parts_parser.config import Settings
from parts_parser.llm import LLMError, OpenAIClient, get_client


def test_get_client_without_api_key_raises_plain_language_error():
    with pytest.raises(LLMError, match="Settings"):
        get_client(Settings(openai_api_key=None))


def test_get_client_returns_openai_client_with_configured_model():
    client = get_client(Settings(openai_api_key="sk-x", model="gpt-5-mini"))

    assert isinstance(client, OpenAIClient)
    assert client._model == "gpt-5-mini"


def test_complete_json_returns_parsed_object(monkeypatch):
    client = OpenAIClient(api_key="sk-x")
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"a": 1}'))]
    )
    monkeypatch.setattr(client._client.chat.completions, "create", lambda **kwargs: response)

    result = client.complete_json(system="Return JSON.", user="Synthetic prompt")

    assert result == {"a": 1}


def test_complete_json_raises_llm_error_for_invalid_json(monkeypatch):
    client = OpenAIClient(api_key="sk-x")
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="not json"))]
    )
    monkeypatch.setattr(client._client.chat.completions, "create", lambda **kwargs: response)

    with pytest.raises(LLMError):
        client.complete_json(system="Return JSON.", user="Synthetic prompt")

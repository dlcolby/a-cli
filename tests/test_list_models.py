from unittest.mock import MagicMock, patch

from ai_cli.providers.anthropic_provider import AnthropicProvider
from ai_cli.providers.openai_provider import OpenAIProvider


def test_anthropic_list_models_live_success():
    provider = AnthropicProvider(api_key="fake")
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"data": [{"id": "claude-sonnet-5"}, {"id": "claude-opus-4-8"}]}
    with patch("ai_cli.providers.anthropic_provider.requests.get", return_value=mock_resp):
        models = provider.list_models()
    ids = {m.model_id for m in models}
    assert ids == {"claude-sonnet-5", "claude-opus-4-8"}


def test_anthropic_list_models_falls_back_on_network_error():
    import requests

    provider = AnthropicProvider(api_key="fake")
    with patch("ai_cli.providers.anthropic_provider.requests.get", side_effect=requests.RequestException("boom")):
        models = provider.list_models()
    aliases = {m.alias for m in models}
    assert "sonnet" in aliases  # curated fallback list, not empty


def test_openai_list_models_filters_non_chat_models():
    provider = OpenAIProvider(api_key="fake")
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "data": [
            {"id": "gpt-5"},
            {"id": "text-embedding-3-small"},
            {"id": "whisper-1"},
            {"id": "dall-e-3"},
        ]
    }
    with patch("ai_cli.providers.openai_provider.requests.get", return_value=mock_resp):
        models = provider.list_models()
    ids = {m.model_id for m in models}
    assert ids == {"gpt-5"}


def test_openai_list_models_falls_back_on_network_error():
    import requests

    provider = OpenAIProvider(api_key="fake")
    with patch("ai_cli.providers.openai_provider.requests.get", side_effect=requests.RequestException("boom")):
        models = provider.list_models()
    aliases = {m.alias for m in models}
    assert "gpt5" in aliases

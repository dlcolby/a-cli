from unittest.mock import MagicMock

from ai_cli import naming
from ai_cli.providers.base import StreamEvent


def test_suggest_title_strips_quotes_and_truncates():
    provider = MagicMock()
    provider.send.return_value = iter([StreamEvent(type="text_delta", text='"fixing the '), StreamEvent(type="text_delta", text='docker build"')])
    title = naming.suggest_title(provider, "haiku", "why is my build failing", "you're missing a base image")
    assert title == "fixing the docker build"


def test_suggest_title_raises_on_provider_error():
    provider = MagicMock()
    provider.send.return_value = iter([StreamEvent(type="error", error="boom")])
    try:
        naming.suggest_title(provider, "haiku", "hi", "hello")
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


def test_suggest_title_falls_back_to_untitled_on_empty_response():
    provider = MagicMock()
    provider.send.return_value = iter([])
    title = naming.suggest_title(provider, "haiku", "hi", "hello")
    assert title == "untitled"

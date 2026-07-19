"""Touch-friendly input UI via prompt_toolkit: typing '/' shows a filterable,
tappable dropdown of commands; '/model ' swaps to a model/provider dropdown;
'/session ' swaps to a session-id dropdown. mouse_support=True is enabled so a
finger tap can select a completion if a-shell forwards touch as SGR mouse
events — this is UNVERIFIED on-device (see plan's UI/library viability spike)
and falls back gracefully to keyboard arrow-key selection if it doesn't work.
"""

from __future__ import annotations

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import FuzzyCompleter, NestedCompleter, WordCompleter

from . import session as session_mod
from .commands.loader import all_command_names
from .providers.registry import PROVIDERS


def _model_words(ctx) -> WordCompleter:
    words = []
    for provider_name, provider_cls in PROVIDERS.items():
        # Instantiate lazily just to read model aliases; api_key unused for listing.
        try:
            provider = provider_cls(api_key="")
            for m in provider.list_models():
                words.append(f"{provider_name}:{m.alias}")
        except Exception:
            continue
    return WordCompleter(words, ignore_case=True)


def _session_words(ctx) -> WordCompleter:
    ids = [s["id"] for s in session_mod.list_sessions(ctx.cwd, ctx.bookmark_root)]
    return WordCompleter(ids, ignore_case=True)


def build_completer(ctx) -> FuzzyCompleter:
    nested = {}
    for name in all_command_names(ctx):
        nested[f"/{name}"] = None

    nested["/model"] = _model_words(ctx)
    nested["/provider"] = WordCompleter(list(PROVIDERS.keys()), ignore_case=True)
    nested["/session"] = {
        "list": None,
        "new": {"--global": None},
        "switch": _session_words(ctx),
        "rm": _session_words(ctx),
    }
    nested["/memory"] = {"append": None}

    return FuzzyCompleter(NestedCompleter.from_nested_dict(nested))


class Repl_UI:
    """Thin wrapper so repl.py doesn't need to know about prompt_toolkit directly."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.session = PromptSession(mouse_support=True, complete_while_typing=True)

    def prompt(self, message: str = "> ") -> str:
        # Rebuild the completer each call since available models/sessions can
        # change between turns (e.g. after /session new).
        self.session.completer = build_completer(self.ctx)
        return self.session.prompt(message)

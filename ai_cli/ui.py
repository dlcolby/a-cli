"""Touch-friendly input UI via prompt_toolkit: typing '/' shows a filterable,
tappable dropdown of commands; '/model ' swaps to a model/provider dropdown;
'/session ' swaps to a session-id dropdown.

mouse_support=True is what makes finger-tap completion selection work, but it
also captures swipe/scroll gestures for the app instead of the terminal's
native scrollback (confirmed on-device: tap-to-select works, but scrollback
stops working while it's on). Since you can't have both at once with a single
xterm mouse-tracking mode, /mouse off|on lets you switch between them: turn it
off to scroll back through chat history, on again to tap-select completions.
"""

from __future__ import annotations

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import FuzzyCompleter, NestedCompleter, WordCompleter

from . import session as session_mod
from .commands.loader import all_command_names
from .providers.registry import PROVIDERS


def _model_words(ctx) -> WordCompleter:
    words = ["refresh"]
    for provider_name in PROVIDERS:
        api_key = ctx.get_api_key(provider_name)
        if not api_key:
            continue  # only list models for providers you've actually configured a key for
        cached = ctx.model_cache.get(provider_name)
        if cached is None:
            try:
                cached = PROVIDERS[provider_name](api_key=api_key).list_models()
            except Exception:
                cached = []
            ctx.model_cache[provider_name] = cached
        for m in cached:
            words.append(f"{provider_name}:{m.alias}")
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
        "rename": None,
    }
    nested["/memory"] = {"append": None}
    nested["/mouse"] = {"on": None, "off": None}

    return FuzzyCompleter(NestedCompleter.from_nested_dict(nested))


class Repl_UI:
    """Thin wrapper so repl.py doesn't need to know about prompt_toolkit directly."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.session = PromptSession(complete_while_typing=True)

    def prompt(self, message: str = "> ") -> str:
        # Rebuild the completer each call since available models/sessions can
        # change between turns (e.g. after /session new). mouse_support is
        # re-read each call too, since /mouse on|off toggles it live.
        self.session.completer = build_completer(self.ctx)
        return self.session.prompt(message, mouse_support=self.ctx.mouse_enabled)

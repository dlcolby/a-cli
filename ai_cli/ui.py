"""Touch-friendly input UI via prompt_toolkit: typing '/' shows a filterable,
tappable dropdown of commands; '/model ' swaps to a model/provider dropdown;
'/session ' swaps to a session-id dropdown.

mouse_support=True is what makes finger-tap completion selection work, but it
also captures swipe/scroll gestures for the app instead of the terminal's
native scrollback (confirmed on-device: tap-to-select works, but scrollback
stops working while it's on). Since a single xterm mouse-tracking mode can't
do both, the default "auto" mode toggles the terminal's actual mouse-reporting
state live: off while you're just typing (scrollback works), on for the brief
window a completion dropdown is visible (tap-to-select works), off again once
it closes. /mouse on|off overrides this with the old fixed behavior if the
dynamic toggling turns out to be unreliable on a given device.
"""

from __future__ import annotations

from prompt_toolkit import PromptSession
from prompt_toolkit.application import get_app
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
    # WORD=True treats the whole dash-separated id (timestamp-title-hash) as one
    # completable token instead of splitting on '-' as a word boundary.
    return WordCompleter(ids, ignore_case=True, WORD=True)


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
        self.session.default_buffer.on_completions_changed += self._on_completions_changed

    def _on_completions_changed(self, buf) -> None:
        """Live-toggle the terminal's actual mouse-reporting mode based on
        whether a completion dropdown is currently showing. Only active in
        "auto" mode — /mouse on|off bypasses this entirely."""
        if self.ctx.mouse_mode != "auto":
            return
        try:
            output = get_app().output
        except Exception:
            return
        if buf.complete_state is not None:
            output.enable_mouse_support()
        else:
            output.disable_mouse_support()

    def prompt(self, message: str = "> ") -> str:
        # Rebuild the completer each call since available models/sessions can
        # change between turns (e.g. after /session new).
        self.session.completer = build_completer(self.ctx)
        # Baseline mouse state for the whole prompt() call: off in "auto" (the
        # completions-changed hook turns it on only while a dropdown is open),
        # matching whichever fixed choice the user picked otherwise.
        base_mouse_support = self.ctx.mouse_mode == "on"
        return self.session.prompt(message, mouse_support=base_mouse_support)

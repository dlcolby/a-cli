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

Note on the dynamic toggle's implementation: Buffer.on_completions_changed
only fires when a dropdown *appears* (prompt_toolkit's _set_completions is the
only place that fires it) — selecting or cancelling a completion clears
complete_state directly without firing that event. So this hooks the
Application's on_invalidate event instead (fires on essentially every redraw
-- text changes, cursor moves, completion state changes, all of it), and also
force-disables mouse support in a finally block after every prompt() call as
a hard reset, so a missed transition can't leave the terminal stuck in mouse
mode between turns.
"""

from __future__ import annotations

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, FuzzyCompleter, NestedCompleter, WordCompleter
from prompt_toolkit.formatted_text import HTML

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
    sessions = session_mod.list_sessions(ctx.cwd, ctx.bookmark_root)
    ids = [s["id"] for s in sessions]
    # display_dict shows "timestamp — title" in the dropdown (reflecting the
    # CURRENT title, e.g. auto-naming/rename results) while still inserting
    # the real id into the buffer when selected — matching stays id-based.
    display = {s["id"]: session_mod.format_session_label(s["created_at"], s["title"]) for s in sessions}
    # WORD=True treats the whole dash-separated id (timestamp-hash) as one
    # completable token instead of splitting on '-' as a word boundary.
    return WordCompleter(ids, ignore_case=True, WORD=True, display_dict=display)


class _SlashOnlyCompleter(Completer):
    """Only delegate to the wrapped completer when the buffer starts with
    '/'. Without this, FuzzyCompleter matches a single typed character
    against ANY top-level command name by subsequence (e.g. "e" fuzzy-matches
    "/help", "/session", "/memory", ...), so with complete_while_typing=True
    a dropdown popped open on almost every keystroke of ordinary chat text,
    not just slash commands (device report, 2026-07-19)."""

    def __init__(self, inner: Completer):
        self.inner = inner

    def get_completions(self, document, complete_event):
        if not document.text_before_cursor.lstrip().startswith("/"):
            return
        yield from self.inner.get_completions(document, complete_event)


def build_completer(ctx) -> Completer:
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
    nested["/mouse"] = {"auto": None, "on": None, "off": None}

    return _SlashOnlyCompleter(FuzzyCompleter(NestedCompleter.from_nested_dict(nested)))


class Repl_UI:
    """Thin wrapper so repl.py doesn't need to know about prompt_toolkit directly."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.session = PromptSession(complete_while_typing=True)
        self._mouse_currently_on = False
        # PromptSession builds one Application in __init__ and reuses it for
        # every prompt() call, so this handler stays attached for the REPL's
        # whole lifetime, not just one turn.
        self.session.app.on_invalidate += self._sync_mouse_state

    def _sync_mouse_state(self, app) -> None:
        """Fires on essentially every redraw (text/cursor/completion-state
        changes) — checked every time rather than assumed from a single
        event, since no single Buffer event reliably covers both a dropdown
        appearing AND being dismissed. Only active in "auto" mode.

        enable/disable_mouse_support() only APPEND the escape codes to the
        output's internal write buffer (confirmed by reading vt100.py) —
        they don't reach the real terminal until something calls flush().
        Without an explicit flush() here, the toggle can sit queued and
        never actually take effect, or take effect late/inconsistently
        depending on unrelated render timing. Flushing immediately makes
        the terminal state change happen when we intend it to."""
        if self.ctx.mouse_mode != "auto":
            return
        should_be_on = self.session.default_buffer.complete_state is not None
        if should_be_on == self._mouse_currently_on:
            return
        output = self.session.app.output
        if should_be_on:
            output.enable_mouse_support()
        else:
            output.disable_mouse_support()
        output.flush()
        self._mouse_currently_on = should_be_on

    async def prompt(self, message: str = "> ") -> str:
        # Rebuild the completer each call since available models/sessions can
        # change between turns (e.g. after /session new).
        self.session.completer = build_completer(self.ctx)
        # Baseline mouse state for the whole prompt() call: off in "auto" (the
        # dynamic hook turns it on only while a dropdown is open), matching
        # whichever fixed choice the user picked otherwise.
        base_mouse_support = self.ctx.mouse_mode == "on"
        self._mouse_currently_on = base_mouse_support
        # Colored prompt marker so it's visually easy to spot where each user
        # turn starts when scrolling back — done via HTML tags rather than raw
        # ANSI, since this text goes through prompt_toolkit's own renderer.
        colored_message = HTML(f"<ansicyan>{message}</ansicyan>")
        try:
            # prompt_async(), not prompt(): the sync prompt() wraps every call
            # in its own asyncio.run(), which creates (and, on return, tears
            # down) a brand-new event loop and kqueue selector every single
            # turn. A device crash (OSError: Errno 22 from selectors.py's
            # kqueue registration) surfaced on an ordinary, non-nested call
            # to this method after several prior turns in the same session —
            # consistent with a-shell's kqueue implementation not tolerating
            # many create/destroy cycles within one process. prompt_async()
            # is meant to be awaited from within an already-running loop
            # (main() now holds one for the REPL's whole lifetime via
            # asyncio.run() at the top level), so only one event loop and one
            # kqueue selector ever exist for the entire session.
            return await self.session.prompt_async(colored_message, mouse_support=base_mouse_support)
        finally:
            # Hard reset: guarantees scrollback works between turns in "auto"
            # mode even if some dismissal path didn't get caught above.
            if self.ctx.mouse_mode == "auto":
                self.session.app.output.disable_mouse_support()
                self.session.app.output.flush()
                self._mouse_currently_on = False

# a-cli: Architecture & Design History

This is the technical design doc for the project (see `README.md` for the user-facing pitch/install instructions). It supersedes the original planning doc and is kept up to date as the implementation evolves — this file, not memory or chat history, is the source of truth for design decisions and open issues going into a new session.

## Context

The user runs OpenCode as their agentic coding/brainstorming CLI on PC and wanted a comparable, genuinely usable CLI experience on their iPhone so they can continue the same "workflow" (skills, long-term notes/memory, project context) while away from the PC. iSH (too heavy on battery/resources) and a remote/SSH-based setup (wants fully on-device execution) were both explicitly ruled out, and the existing `a-agent` tool was rejected as too bare-bones (no slash commands). This is a from-scratch Python CLI that runs inside **a-shell**, is LLM-agnostic, and reads/writes the *same* on-disk conventions OpenCode already uses (skills, `AGENTS.md`, slash commands) rather than inventing an incompatible format, so PC and mobile can genuinely share state via a synced folder.

## Confirmed on-device (2026-07)

- **a-shell**: Python 3.11-ish; `pip install` only works for pure-Python packages (no C-extension wheels — rules out numpy/cryptography-style deps; `requests`/`pyyaml`/`prompt_toolkit` are all pure Python and fine). Custom commands are executable scripts dropped into `~/Documents/bin/`. The app is suspended in the background like any iOS app — no continued execution once backgrounded, so the tool is a foreground-only interactive REPL by design.
- **Networking**: real outbound HTTPS from a-shell's Python works, including genuinely incremental streaming (confirmed via a drip-test endpoint — chunks arrived spread over several seconds, not buffered until the end). Streaming-by-default in the providers is safe.
- **prompt_toolkit**: installs and runs correctly in a-shell's terminal; completion dropdowns render, and tapping a specific item out of several visible candidates with a finger correctly selects it (not just a keyboard-arrow fallback).
- **a-shell has no full `git`** — use its bundled `lg2` command (`lg2 clone`, `lg2 fetch` + `lg2 reset --hard origin/main` if `lg2 pull` isn't supported) instead.
- **a-shell's shell is POSIX `sh`, not `bash`** — `bootstrap.sh` is written accordingly (`set -eu`, not `set -euo pipefail`; `$0`-based path resolution, not `$BASH_SOURCE`).
- **litellm was evaluated and rejected**: hard-requires `tiktoken`/`tokenizers` (Rust/PyO3) and `pydantic>=2` (`pydantic-core` is Rust) — none buildable under a-shell's pure-Python-only pip, no minimal extra avoids them. The hand-rolled `Provider` ABC is therefore the actual LLM-agnostic mechanism, deliberately thin to avoid this class of dependency.

## OneDrive: known limitation, deliberate workaround

`pickFolder` (a-shell's folder-bookmarking command, using iOS's document-picker API) works cleanly for **iCloud Drive** — browsing into a folder and tapping "Open" bookmarks it. For **OneDrive**, exhaustive on-device troubleshooting (checking the OneDrive app's own settings, confirming it's up to date, trying a different top-level folder, double-checking the exact tap sequence, confirming OneDrive shows up as a location the same way iCloud does) all converge on the same result: **OneDrive folders never become selectable in `pickFolder`** ("Open" never enables). This is a genuine limitation of OneDrive's iOS Files-provider extension (no persistent folder-level access grants to other apps), not something fixable from a-shell or iOS settings.

- **Decision**: the user is committed to the OneDrive ecosystem and declined switching to iCloud Drive. Current workaround: use a plain local a-shell folder as `bookmark_root` (no live sync), and manually move files in/out via OneDrive's own "Save a copy"/"Export". Zero new code, unblocks everything else.
- **Deferred real fix** (not started): bypass the Files-provider layer entirely via direct Microsoft Graph API access (OAuth device-code flow + HTTPS to `https://graph.microsoft.com/v1.0/me/drive/...`, same `requests`-based approach as the LLM providers). Would need a real refactor: `memory.py`/`skills.py`/`session.py`/`commands/markdown_command.py` currently do direct `pathlib.Path` I/O against `bookmark_root` and would need a storage-backend abstraction (local filesystem vs. Graph API), plus OAuth token acquisition/refresh with secure local-only storage (same rule as API keys — never synced).

## File layout

**Local-only (a-shell filesystem, never synced):**
```
~/Documents/bin/aic                  # launcher script, written by bootstrap.sh, points back at the clone
~/Documents/.mobilecli/secrets.json  # API keys — must never live under bookmark_root
~/Documents/.mobilecli/config.json   # bookmark_root path, default provider/model
```
(Code itself lives wherever the repo was cloned, e.g. `~/Documents/a-cli/` — `bootstrap.sh` hardcodes that path into the launcher at install time.)

**Shared workflow folder (`bookmark_root`, intended for OneDrive, currently a local folder — see above):**
```
<bookmark_root>/
  AGENTS.md                             # global shared memory (falls back to CLAUDE.md)
  .opencode/skills/<name>/SKILL.md
  .opencode/commands/<name>.md
  mobile_sessions/<id>.json             # GLOBAL sessions — visible from any directory
  <project>/AGENTS.md                   # project-scoped memory
  <project>/.opencode/...
  <project>/mobile_sessions/<id>.json   # PROJECT-scoped sessions — only visible when cwd is under <project>
```

Session scoping: `/session list` shows the nearest `mobile_sessions/` walking up from cwd to `bookmark_root`, plus the bookmark-root-level one (global, always visible). A project directory is recognized by containing `AGENTS.md`, `CLAUDE.md`, `.opencode/`, or an existing `mobile_sessions/`.

## Repo layout (`ai_cli/` package)

- `providers/base.py` — `Provider` ABC (`send()`, `list_models()`). This ABC, not a third-party SDK, is the LLM-agnostic mechanism.
- `providers/anthropic_provider.py`, `providers/openai_provider.py` — raw `requests` calls (Anthropic `/v1/messages` SSE; OpenAI `/v1/chat/completions` SSE), streaming with a non-streaming fallback path. `list_models()` live-queries each provider's `GET /v1/models` (falling back to a small curated alias table if the call fails), so the model dropdown only reflects providers you've actually configured a key for.
- `providers/registry.py` — provider registry + `CHEAP_MODEL_BY_PROVIDER` (Haiku / GPT-5 mini) used for auxiliary tasks like session auto-naming.
- `memory.py` — loads global + project `AGENTS.md`/`CLAUDE.md` into the system prompt.
- `skills.py` — OpenCode-compatible skill discovery (`.opencode/skills/`, `.claude/skills/`, `.agents/skills/`, project overrides global). Only name+description go in the system prompt; full `SKILL.md` body is fetched on demand via a `read_skill` pseudo-tool.
- `session.py` — session store. Ids are `<timestamp>-<hash>` (no title-derived slug — see Known Issues history below for why that changed), atomic writes, a generated `.md` mirror, `format_session_label()` for human-readable dropdown display, `format_transcript()` (color-coded) for reprinting history on `/session switch`.
- `commands/builtin.py` — `/model`, `/provider`, `/session`, `/skills`, `/memory`, `/mouse`, `/new`, `/help`, `/exit`.
- `commands/markdown_command.py` — OpenCode-style `.opencode/commands/*.md` parser (`$ARGUMENTS`, `$1`, `@file`; `` !`shell` `` interpolation deliberately disabled by default).
- `ui.py` — `prompt_toolkit`-based input loop: `NestedCompleter`+`FuzzyCompleter` for touch-friendly dropdowns, plus the mouse-mode handling (see Known Issues — **currently broken**).
- `naming.py` — auto-proposes a short session title from the first exchange using a cheap model; best-effort, never blocks a chat turn on failure.
- `colors.py` — minimal ANSI helpers; cyan user-prompt marker, green assistant replies, red errors, yellow system notices, magenta `[tool]` call descriptions, bold-yellow confirmation prompts — aimed at making it easy to spot turn boundaries, and to distinguish agentic tool activity/confirmations from normal chat, when scrolling back.
- `config.py` — secrets precedence (env var > `secrets.json` > interactive prompt); startup guard asserting secrets never live under `bookmark_root`.
- `context.py` — `AppContext`, the mutable state threaded through commands/REPL.
- `repl.py` — the main loop, including a simplified single-tool (`read_skill`) tool-call loop.

## Distribution

GitHub repo (`dlcolby/a-cli`) cloned directly on-device via `lg2 clone`. `bootstrap.sh` installs pure-Python deps, sets up `~/Documents/.mobilecli/`, and writes the `~/Documents/bin/aic` launcher. First run of `aic` prompts for an API key and the shared-folder path (no OneDrive/pickFolder integration in-app — see above).

Note: an earlier version of this plan described a conversational `/setup` onboarding command (LLM-guided folder picking / scaffolding). **This was never implemented** — first-run setup is a plain sequential prompt (API key, then folder path), not an LLM-driven flow. Revisit if that gap turns out to matter in practice.

## Agentic capability (implemented, 2026-07-19)

Goal: give `aic` enough capability to read/write files and execute commands, so
it can test and fix its own code rather than being read-only. Built in two
parts — a structured tool-call loop, and the tools themselves.

**Execution feasibility, confirmed on-device (spike 4, `tests/spikes/spike4_execute.py`):**
`subprocess.run`/`Popen` (including `shell=True`) and `os.system`/`os.popen` all
work in a-shell's Python. **`os.fork()` does not** — it triggers a Fatal Python
error (`PyMutex_Unlock: unlocking mutex that is not locked`) that hangs the
entire a-shell app with no catchable exception; recovery requires force-quitting
a-shell. `multiprocessing.Process` is ruled out by the same finding, since its
default POSIX start method is fork-based. **Design rule, enforced in
`agent_tools.py`: `run_command` is built exclusively on `subprocess.run`; never
`os.fork`/`multiprocessing`.**

**`Message.content` is now `str | list[dict]`** (`providers/base.py`): plain
text turns stay a string (no behavior change, no format churn in existing
sessions); turns involving tool use carry a list of content blocks mirroring
Anthropic's own native shape (`text`/`tool_use`/`tool_result` blocks, via the
`text_block()`/`tool_use_block()`/`tool_result_block()` helpers). Anthropic's
`_body()` passes this through unchanged since it's already Anthropic's wire
format. `OpenAIProvider._to_openai_messages()` translates it into Chat
Completions' own shape instead — an assistant message's `tool_calls` array for
`tool_use` blocks, and separate `"tool"`-role messages (keyed by
`tool_call_id`) for `tool_result` blocks, since OpenAI has no user-role tool
result the way Anthropic does. `content_to_text()` flattens either shape back
to a plain string for the session's markdown mirror, `/session switch`'s
transcript reprint, and auto-naming — none of those need block-level
structure, just human-readable text.

**Tool set** (`agent_tools.py`): `read_file`, `write_file`, `run_command`, all
scoped to `project_dir` (or `bookmark_root` if there's no project) via
`_resolve_scoped_path()` — a path that resolves outside that root raises
`ToolError` rather than running, the same instinct as the secrets-isolation
guard in `config.py`. `write_file` and `run_command` are gated in `repl.py`'s
`_run_tool_call()` behind an interactive `y/N` confirmation (plain `input()`,
called after `ui.py`'s `prompt_toolkit` `Application` has already returned for
that turn, so there's no terminal-mode conflict) before they execute — a
declined call becomes an `is_error` tool_result the model sees, not a crash.
`read_file`/`read_skill` need no confirmation. `MAX_TOOL_ROUNDS` raised from 4
to 12 to allow real read→write→run sequences instead of just one skill lookup.

Not yet done: no opt-out toggle to disable agent tools entirely (e.g. for a
read-only chat session) — every turn currently offers the model file
read/write/run capability, protected only by the confirmation gate. Revisit if
that turns out to matter in practice.

**Confirmation prompt hard-hung a-shell on-device (found + fixed, 2026-07-19):**
the original `_confirm()` in `repl.py` used a bare `input()` call for the
`write_file`/`run_command` y/N gate, on the assumption (stated in the original
comment, never actually verified on a real device) that since
`prompt_toolkit`'s `Application` had already returned for the turn there'd be
no terminal-mode conflict. Confirmed wrong on-device: triggering a `run_command`
tool call (a `find` command) and hitting the confirmation prompt hard-hung
a-shell — no echo, unrecoverable, force-quit required, the same class of
symptom as the `os.fork()` finding in spike 4. Most likely cause: a bare
`input()` doesn't negotiate whatever raw-mode/mouse-tracking terminal state
`prompt_toolkit` leaves behind, unlike `prompt_toolkit`'s own input path, which
*is* confirmed working on-device (streaming, completion dropdowns). **Fix**:
added `Repl_UI.confirm()` in `ui.py`, which reuses the same `PromptSession`
(explicitly forcing mouse support off first, regardless of `ctx.mouse_mode`,
then restoring the "auto" hard-reset in a `finally`) instead of a separate
`input()` call. `AppContext` gained a `repl_ui` field (`main()` sets it after
constructing `Repl_UI`); `repl.py`'s `_confirm()` now routes through
`ctx.repl_ui.confirm()` when present and only falls back to bare `input()`
when there's no UI attached (the PC test suite's `AppContext`s, which
monkeypatch `builtins.input` directly).

**That first fix attempt still crashed on-device (2026-07-19, same day)**: two
new symptoms. (1) typing `"y"` at the confirmation prompt popped a completion
dropdown. (2) that then produced a hard crash — traceback bottoming out in
`selectors`/`asyncio`'s `loop.add_reader` raising `OSError: [Errno 22] Invalid
argument`, via `prompt_toolkit`'s `vt100.py` `_attached_input` /
`shortcuts/prompt.py`'s `app.run()`, from `Repl_UI.confirm()`'s
`self.session.prompt(...)` call. Root cause of (1): `confirm()` reused
`self.session`, which still had whatever `NestedCompleter` +
`complete_while_typing=True` was left set from the *previous* regular
`prompt()` call — `FuzzyCompleter` matches a single character against almost
anything, so `"y"` triggered a dropdown. Root cause of (2), following from
(1): that dropdown appearing changed `complete_state`, which fired the
`on_invalidate` auto-mouse hook (`_sync_mouse_state`, still attached to
`self.session.app` since `confirm()` never touched it) — the hook doesn't know
this particular call asked for `mouse_support=False`, so it called
`output.enable_mouse_support()` on an `Application` explicitly configured
without mouse support. That mismatch between the Application's compiled-in
mouse configuration and the raw escape codes being pushed at runtime is the
most likely cause of the `EINVAL` in the input-registration path. **Fix v2**:
`confirm()` now passes `completer=None, complete_while_typing=False` as
per-call overrides to `session.prompt()` (not mutating session state, so
nothing needs restoring) and detaches `_sync_mouse_state` from
`self.session.app.on_invalidate` for the duration of the call, re-attaching it
in the `finally` — so nothing can flip mouse support mid-call regardless of
completion state. Covered by new regression tests in
`tests/test_ui_mouse_hook.py` (`test_confirm_disables_completion_for_this_call`,
`test_confirm_detaches_and_reattaches_auto_mouse_hook`). **Still not
device-confirmed** — this is now two device round-trips into the same code
path; treat it as reasoned-but-unverified until the user reports back.

## Known issues / open actions

1. **`/mouse auto` mode does not reliably work — OPEN, unresolved after two fix attempts.** Goal: dynamically enable touch-tap completion selection only while a dropdown is visible, and native terminal scrollback the rest of the time (both rely on the same xterm mouse-tracking mode, so can't be on simultaneously).
   - **Attempt 1**: hooked `Buffer.on_completions_changed`. Root-caused as wrong: that event only fires when a dropdown *appears* (`_set_completions`) — selecting/cancelling clears `complete_state` directly without firing it, so mouse mode turned on but never back off.
   - **Attempt 2**: switched to `Application.on_invalidate` (fires on every redraw) plus a hard `disable_mouse_support()` in a `finally` block after every `prompt()` call. Also discovered and fixed that `enable_mouse_support()`/`disable_mouse_support()` only append escape codes to an internal output buffer (confirmed by reading `prompt_toolkit`'s `vt100.py`) — added explicit `.flush()` calls after every toggle.
   - **Still reported broken on-device** as of this writing (user report: "auto mouse feature is still not working" — most recent report before that was "not disabling scrolling properly and allowing for a selection, when the dropdown box appears," i.e. seemingly not toggling on either). The flush fix has not yet been re-tested/confirmed against that specific complaint.
   - **Next steps to try**: instrument with on-device debug output (e.g. print the raw escape bytes being written, or log every `_sync_mouse_state` call with before/after state) rather than guessing further from source-reading alone; consider whether a-shell's terminal has its own quirk around receiving `\x1b[?1000h`/`\x1b[?1006h` etc. mid-session vs. only at app startup; as a pragmatic fallback, the fixed `/mouse on` / `/mouse off` modes work as designed (per user's earlier confirmation) — `auto` is a nice-to-have layered on top, not required for basic usability.
2. **OneDrive `pickFolder` folder-selection is unsupported** — see dedicated section above. Working around it with a local folder; Graph API integration is the real fix, not started.
3. **OpenAI provider path is implemented but not yet device-tested** — only the Anthropic path has been exercised live on the phone so far (`/model openai:...` and the OpenAI SSE parsing are covered by unit tests, not a real on-device call).
4. **`/setup` conversational onboarding described in early planning was never built** (see Distribution note above) — not currently a gap the user has asked to fill, noted for completeness.
5. **Tool-confirmation prompt fix needs on-device re-test — OPEN.** See "Confirmation prompt hard-hung a-shell on-device" above: `_confirm()` now goes through `Repl_UI.confirm()` (same `PromptSession`) instead of bare `input()`. Reasoned fix, not yet confirmed against the actual on-device hang.

## Verification approach

- **PC-testable** (`pytest`, no device needed): provider SSE/response parsing against recorded fixtures, live-model-list fallback behavior, slash-command parsing, skill/memory discovery, session store round-tripping and scoping, the mouse-toggle hook's logic in isolation (mocked `Buffer`/`Application`), secrets-isolation guard.
- **Device-only**: everything in Known Issues above, plus `~/Documents/bin` registration surviving app kill/reboot, real network behavior over WiFi/cellular, `bootstrap.sh` on a clean install, and general end-to-end usability.

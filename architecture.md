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

Session scoping: `/session list` shows the nearest `mobile_sessions/` walking up from cwd to `bookmark_root`, plus the bookmark-root-level one (global, always visible). A project directory is recognized by containing `AGENTS.md`, `CLAUDE.md`, `.opencode/`, `.git/`, or an existing `mobile_sessions/`.

**Expected: a fresh clone loses sessions but keeps config/secrets.** If `bookmark_root` (or a project under it) is itself a git-managed clone of a repo — e.g. using the a-cli repo's own working copy as a project directory, which is how it's actually been dogfooded — then a `lg2 clone`/reclone of that repo wipes `mobile_sessions/*.json` (it's gitignored, never committed, so a fresh clone naturally starts without it) while `~/Documents/.mobilecli/secrets.json`/`config.json` (API keys, default provider/model, the `bookmark_root` path itself) are untouched, since they live entirely outside the cloned repo. This is by design, not a bug — session history for a project stored this way doesn't survive a reclone of that project's own repo.

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
completion state.

**Fix v2 also failed on-device (2026-07-19, third round-trip), proving the
whole strategy wrong, not just a detail of it.** Two separate on-device runs
of the *same* v2 code: first run, the confirm succeeded (typed `y`, model
started responding) but a-shell then hard-crashed with no traceback at all
during/after the follow-up response — and because saving only happened at
the very end of `send_turn()`, the entire exchange (including the user's
original request) was lost on reopen. Second run, same command, crashed
immediately at the confirmation prompt itself with the *exact same* `OSError:
[Errno 22] Invalid argument` at the *exact same line* (`ui.py`'s
`self.session.prompt(...)` inside `confirm()`) as fix v1 — despite the
completer/mouse-hook fix. That recurrence is the key data point: it means the
v1 diagnosis (dropdown → mouse-hook mismatch) wasn't the real root cause, or
at best was only one of several. The one constant across all three device
round-trips is calling `Application.run()` (via `session.prompt()`) a second
time within the same process mid-turn — sometimes it hangs (pre-fix bare
`input()`, if the terminal was left in a state `input()` couldn't read),
sometimes it raises `EINVAL` from `selectors.py`'s kqueue-based reader
registration, sometimes it corrupts state invisibly until a *later* crash
with no traceback. **Conclusion: a second nested `Application.run()`
mid-turn is unreliable on a-shell's asyncio+kqueue combination, full stop —
not a bug to patch around, a strategy to abandon.**

**Fix v3 (current): stop touching `prompt_toolkit`'s `Application` for this
at all.** `Repl_UI.confirm()` is gone, replaced by `Repl_UI.disable_mouse_now()`
— a pure output-level escape-code write + flush, not a run loop, so it can't
hit the kqueue issue. `repl.py`'s `_confirm()` now: calls
`ctx.repl_ui.disable_mouse_now()` if a UI is attached, then — since the v1
hang shows the terminal can't be trusted to already be in a normal
(canonical+echo) state after a prior `Application.run()` — explicitly forces
it there itself via `termios.tcsetattr()` (guarded by `try/except
ImportError` at module scope, since `termios` doesn't exist on the Windows PC
running the test suite), then falls back to a plain `input()` call, restoring
the original terminal attributes in a `finally`. Also added incremental
`session_mod.save_session()` calls after every message append in `send_turn()`
(previously only saved once, at the very end) so a crash anywhere mid-turn —
whatever eventually causes it — no longer loses the whole exchange.

**Fix v3's termios patch froze the terminal on-device instead (2026-07-19,
fourth round-trip).** Typing `"y"` echoed nothing and the app just sat there
— no crash, no traceback, genuinely stuck. v3's termios logic patched
`ICANON`/`ECHO` onto whatever *live* lflags were currently set (i.e.
whatever raw-mode state `prompt_toolkit` had left the terminal in) rather
than restoring a full snapshot. Best explanation: POSIX termios reuses the
same `c_cc` array slots for different purposes depending on `ICANON`
(`VMIN`/`VTIME` control blocking behavior in raw/non-canonical mode;
`VEOF`/`VEOL` replace those same slots in canonical mode). `prompt_toolkit`
likely sets `c_cc[VMIN] = 0` for non-blocking raw reads; flipping `ICANON`
back on without touching `c_cc` reinterprets that same byte as `VEOF`
(end-of-file character), which can silently break canonical line-reading —
`input()`'s underlying `readline()` never sees a completed line the way it
expects, so it blocks forever with no exception to catch.

**Fix v4 (current): stop patching live attributes — restore a full pristine
snapshot instead.** `main()` now captures `termios.tcgetattr(stdin_fd)`
*once*, into `ctx.pristine_termios`, before `Repl_UI`/`PromptSession` is even
constructed (i.e. before `prompt_toolkit` has ever had a chance to touch the
terminal) — this snapshot is guaranteed internally consistent (correct
`c_cc` semantics for whatever mode it's in) since it's literally the
terminal's own original state, never hand-patched. `_confirm()` now: captures
whatever *live* attrs are current (to restore afterward), restores
`ctx.pristine_termios` verbatim, calls `input()`, then restores the captured
live attrs in a `finally` — so `prompt_toolkit`'s next regular `prompt()`
call picks back up in whatever raw state it expects. Covered by
`tests/test_repl_tool_loop.py`'s
`test_confirm_restores_pristine_termios_snapshot_when_available`,
`test_confirm_skips_termios_when_unavailable`, and
`test_confirm_skips_termios_when_no_pristine_snapshot_captured`.

**Also added: `ai_cli/debug_log.py`, opt-in diagnostic logging for exactly
this class of bug.** No-op unless `AIC_DEBUG_LOG=<path>` is set in the
environment before running `aic`; each call opens, writes, and closes the
file immediately (no buffering to lose on a freeze/crash that never shuts
down cleanly). `_confirm()` is instrumented at every step (mouse-disable,
termios availability, before/after each `tcsetattr`, immediately before and
after the `input()` call itself — the line most likely to reveal exactly
where a future freeze happens, since "logged 'calling input()' but never
logged 'input() returned'" pins the hang to that exact call). `main()`'s loop
also now wraps command dispatch/`send_turn()` in a broad
`try/except Exception` that logs the full traceback via `debug_log.log()`
before re-raising, so even an exception that doesn't print visibly to
a-shell's console (as happened with one of the v2 crashes) still leaves a
trace on disk. See `tests/spikes/debug_logs/README.md` for the exact
commands to capture and commit a trace after reproducing an issue.

**v4 also froze on-device (2026-07-19, fifth round-trip) — and this time the
`AIC_DEBUG_LOG` trace actually paid off.** The trace shows:
```
_confirm: captured live termios lflag=392
_confirm: restored pristine termios lflag=392
_confirm: calling input()
<nothing after — froze here>
```
**The live and pristine `lflag` values are identical.** The terminal was
never in a different raw-mode state to begin with — termios was never the
actual variable across any of v1/v3/v4 (all three are "call `input()`
[optionally with some termios tweak] after a `prompt_toolkit` `Application`
has run at least once in the process," and all three hang identically
regardless of what termios says). The one thing every hang shares, and the
one thing that's actually confirmed to receive input on this device
(streaming, completion dropdowns, multi-turn `prompt()` calls), is
`prompt_toolkit`'s own `asyncio`-integrated `Application.run()`. Best current
theory: a-shell's terminal likely only delivers keystrokes into the process
while something has an active `asyncio` reader registered on the fd (i.e.
while a `prompt_toolkit` `Application` is actually running) — a plain
blocking `input()`/`read()` outside that may simply never get serviced,
hanging forever with nothing to catch, which is exactly what's been observed
three separate times now. v2's approach (nested `session.prompt()`) was the
only one that actually used that mechanism, but it always reused the *same*
`self.session`/`Application` object, which crashed on re-registering a
reader for the same fd — untested variant: a genuinely fresh, independent
`PromptSession()` (not reusing `self.session`) for the confirmation might
avoid that specific crash if it's about Python-object-level reuse rather
than a true OS-level fd conflict. Not yet tried. See Known Issues #5 for
where this stands and the options being considered next.

**Resolution (2026-07-19): abandoned the nested-synchronous-read strategy
entirely — confirmation now defers to the next normal chat turn.** Discussed
the "fresh `PromptSession`" option vs. restructuring with the user: a fresh
session object still shares the same fd and (most likely) the same
`asyncio` event loop as the one round 2 crashed in, so it was a genuine
coin-flip on which of two unconfirmed theories (Python-object-level state
vs. OS/fd-level state) was actually at fault — not a real fix, just another
guess requiring a sixth device round-trip. The restructuring approach
sidesteps the question entirely: it never calls `Application.run()`/
`session.prompt()` a second time mid-turn, so it can't hit this bug class
regardless of which theory is correct.

**New design.** `_advance_tool_calls()` (`repl.py`) walks a round's tool
calls in order, executing each immediately unless it's in
`agent_tools.CONFIRM_BEFORE_NAMES` (`write_file`/`run_command`) — for those,
it prints what the model wants to do and *pauses*, storing everything needed
to resume onto `ctx.pending_confirmation` (the model/agent_root/tools/
rounds-left for this turn, the remaining not-yet-executed tool calls, and
the tool results already computed earlier in this same round), then returns
control all the way up to `main()`'s loop — no read happens here at all.
`main()`'s loop checks `ctx.pending_confirmation` before treating the next
typed line as a new chat message: if set, it routes to
`resume_pending_confirmation()` instead, which executes or declines the
pending tool call and calls back into `_advance_tool_calls()` to continue
the round (processing any further tool calls in that same round, or pausing
again if another one also needs confirmation). A slash command typed while a
confirmation is pending still runs normally (so `/exit` etc. remain
available as an escape hatch) — but a markdown command's `chat_turn` output
is blocked with a warning telling the user to resolve the pending
confirmation first, rather than silently dropping either one.

**Decline-with-feedback**: a bare `y`/`yes` (case-insensitive, trimmed)
proceeds; a bare `n`/`no`/empty reply declines with no extra detail; anything
else typed is treated as a decline *and* passed back to the model verbatim
("User declined to run this tool call and said: ..."), so declining doubles
as redirection (e.g. "no, use `-maxdepth 2` instead") rather than a dead end.
`AGENT_TOOLS_PROMPT_BLOCK`'s wording was updated to match.

**UX tradeoffs, discussed with the user before building this**: the
confirmation now looks like an ordinary chat prompt rather than a distinct
inline `[y/N]` sub-prompt; the answer becomes a real message in
`session.messages`/the saved transcript (previously an in-memory bool that
was never persisted); Ctrl-C/EOF while a confirmation is pending now behaves
like everywhere else in the app (graceful `/exit` via the main loop's
existing handler) instead of being an untested special case; and a turn that
needs two separate confirmations now surfaces as two visibly distinct
pause/resume steps rather than one continuous nested exchange. Accepted as a
reasonable tradeoff for actually working reliably, given five straight
device round-trips of the alternative.

**Removed as part of this fix** (no longer needed since there's no nested
read to protect against): `_confirm()`, `ui.Repl_UI.disable_mouse_now()`,
`AppContext.pristine_termios`, and the `termios` import/pristine-snapshot
capture in `main()`. `ai_cli/debug_log.py` and its use in `main()`'s broad
exception logger are kept — still generically useful for any future
device-only bug, not specific to this one.

**The defer-to-next-turn fix crashed anyway (2026-07-19, sixth round-trip) —
but the traceback reframes the whole investigation.** The crash this time
was NOT in any confirmation code at all:
```
File "ai_cli/repl.py", line 277, in main
    line = repl_ui.prompt()
File "ai_cli/ui.py", line 156, in prompt
    return self.session.prompt(colored_message, mouse_support=base_mouse_support)
...
File "asyncio/selector_events.py", line 279, in _add_reader
    self._selector.register(fd, selectors.EVENT_READ, (handle, None))
File "selectors.py", line 505, in register
    self._selector.control([kev], 0, 0)
OSError: [Errno 22] Invalid argument
```
This is the exact same `EINVAL`/kqueue-registration error as v2's crash
(round 2, way back near the top of this section) — except this time it hit
the completely ordinary, never-nested, top-level `repl_ui.prompt()` call in
`main()`'s loop, on roughly the *fifth* `prompt()` call of that session (per
the transcript captured alongside the traceback: "read README" → "yes,
please" → "y" → this one). **That retroactively invalidates the "nesting is
the problem" diagnosis from v2 onward** — the same crash can happen on a
plain, never-nested call, just later in a session. The pattern (fine for a
few calls, fails after several more accumulate) points at a different
mechanism: `prompt_toolkit`'s synchronous `.prompt()` calls
`Application.run()`, which internally does `asyncio.run(coro)` — and
`asyncio.run()` creates a **brand-new event loop, and therefore a brand-new
kqueue selector, on every single call**, tearing it down again when that
call returns. That happens once per turn, for the life of the process.
Leading theory: a-shell's kqueue implementation doesn't cleanly tolerate
many create/destroy cycles of kqueue descriptors within one process, and
eventually one of the later registrations fails.

**Fix: hold one persistent event loop for the REPL's entire lifetime,
instead of one per turn.** `main()` is now `_main_async()`, run via a single
`asyncio.run(_main_async(argv))` at the very top (the actual `main()` is now
just that one-line synchronous wrapper). `Repl_UI.prompt()` is now `async
def`, using `await self.session.prompt_async(...)` instead of the sync
`.prompt()` — `prompt_async()` is meant to be awaited from inside an
already-running loop rather than creating its own, so only one event loop
and one kqueue selector ever exist for the whole session, regardless of how
many turns it has. `send_turn()`/`resume_pending_confirmation()`/tool
execution remain fully synchronous (blocking HTTP/subprocess calls) — no
concurrency is needed, they're just called directly from within the async
loop body, which is fine since nothing else needs to run concurrently while
they block. Also fixed in the same pass: the main loop's crash-logging
`try/except` didn't actually cover the `prompt()` call site itself (only
command dispatch/`send_turn()`), which is why this crash produced a raw
traceback with no matching `debug_log` entry — extended the logging to cover
it too. Covered by `tests/test_ui_mouse_hook.py`'s
`test_prompt_uses_prompt_async_not_sync_prompt`.

**Not yet device-confirmed.** Unlike the confirmation-flow rewrite (which was
untested but architecturally novel), this fix targets a hypothesis inferred
from one crash's timing pattern — plausible, and it directly addresses the
actual mechanism (`asyncio.run()` per call) rather than patching around a
symptom, but it's still a hypothesis. If sessions still crash after enough
turns with this in place, the "many kqueue create/destroy cycles" theory
would need to be reconsidered.

**The persistent-event-loop fix helped, but a new crash surfaced — with a
different errno, pointing at `run_command` inheriting stdin (2026-07-19,
seventh round-trip).** Progress: the session got through 7 confirmed prompts
this time (vs. 5 before it crashed last round), and the crash was a
*different* error — `OSError: [Errno 9] Bad file descriptor`, not the
earlier `Errno 22`/`EINVAL`. Same call site (`vt100.py`'s `_attached_input`
→ `loop.add_reader` → `selectors.py`'s `register`), but this time the fd
itself had gone bad, not just failed to register. The key correlated
variable across the two crashes isn't just "how many `prompt()` calls
happened" — it's how many **`run_command` executions** had happened first:
1 before the previous crash, 3 before this one (`ls -la`, `pwd`,
`ls -la ... && find ...`, all executed and confirmed successfully before the
4th confirmation's subsequent `prompt()` call died). `run_command`
(`agent_tools.py`) called `subprocess.run(command, shell=True, cwd=root,
capture_output=True, text=True, timeout=...)` with no `stdin=` argument,
meaning the executed command **inherits the real terminal's stdin (fd 0)**
by default. On a normal POSIX system that's harmless (fork() gives the child
process its own independent file descriptor table pointing at the same
open file description; the parent's fd is untouched regardless of what the
child does with its copy) — but a-shell can't use real `fork()` at all
(spike 4: it hangs the whole app), so whatever `subprocess.run`/`Popen`
shim a-shell actually uses under the hood is necessarily something other
than fork+exec+dup2, and it's plausible that shim doesn't isolate the
child's stdin as cleanly as a real subprocess would — leaving fd 0 in a
degraded state after enough uses, which the *next* `prompt_toolkit` read
then discovers via `EBADF`. **Fix**: added `stdin=subprocess.DEVNULL` to the
`subprocess.run()` call in `run_command()` — the executed command now never
has a path to touch the real terminal fd at all, regardless of the exact
mechanism a-shell uses to run it. Covered by
`tests/test_agent_tools.py`'s `test_run_command_never_inherits_real_stdin`.
**Not yet device-confirmed.**

## Known issues / open actions

1. **`/mouse auto` mode does not reliably work — OPEN, unresolved after two fix attempts.** Goal: dynamically enable touch-tap completion selection only while a dropdown is visible, and native terminal scrollback the rest of the time (both rely on the same xterm mouse-tracking mode, so can't be on simultaneously).
   - **Attempt 1**: hooked `Buffer.on_completions_changed`. Root-caused as wrong: that event only fires when a dropdown *appears* (`_set_completions`) — selecting/cancelling clears `complete_state` directly without firing it, so mouse mode turned on but never back off.
   - **Attempt 2**: switched to `Application.on_invalidate` (fires on every redraw) plus a hard `disable_mouse_support()` in a `finally` block after every `prompt()` call. Also discovered and fixed that `enable_mouse_support()`/`disable_mouse_support()` only append escape codes to an internal output buffer (confirmed by reading `prompt_toolkit`'s `vt100.py`) — added explicit `.flush()` calls after every toggle.
   - **Still reported broken on-device** as of this writing (user report: "auto mouse feature is still not working" — most recent report before that was "not disabling scrolling properly and allowing for a selection, when the dropdown box appears," i.e. seemingly not toggling on either). The flush fix has not yet been re-tested/confirmed against that specific complaint.
   - **Next steps to try**: instrument with on-device debug output (e.g. print the raw escape bytes being written, or log every `_sync_mouse_state` call with before/after state) rather than guessing further from source-reading alone; consider whether a-shell's terminal has its own quirk around receiving `\x1b[?1000h`/`\x1b[?1006h` etc. mid-session vs. only at app startup; as a pragmatic fallback, the fixed `/mouse on` / `/mouse off` modes work as designed (per user's earlier confirmation) — `auto` is a nice-to-have layered on top, not required for basic usability.
2. **OneDrive `pickFolder` folder-selection is unsupported** — see dedicated section above. Working around it with a local folder; Graph API integration is the real fix, not started.
3. **OpenAI provider path is implemented but not yet device-tested** — only the Anthropic path has been exercised live on the phone so far (`/model openai:...` and the OpenAI SSE parsing are covered by unit tests, not a real on-device call).
4. **`/setup` conversational onboarding described in early planning was never built** (see Distribution note above) — not currently a gap the user has asked to fill, noted for completeness.
5. **Terminal-input crash saga, seven device round-trips, converging on `run_command`'s stdin inheritance — OPEN pending device confirmation.** v1-v4 chased a nested-synchronous-read theory for the confirmation prompt specifically; round 5's defer-to-next-turn rewrite then crashed anyway on a plain top-level `prompt()` call with no nesting at all (`EINVAL`), reframing the investigation around `asyncio.run()`-per-call kqueue churn; round 6 held one persistent event loop for the REPL's lifetime, which helped (got through more turns) but round 7 still crashed — this time `EBADF`, correlated with how many `run_command` calls had executed beforehand rather than raw `prompt()` count. Fix (round 7): `run_command` now passes `stdin=subprocess.DEVNULL`, since it was inheriting the real terminal's stdin by default and a-shell's non-standard (fork-less) subprocess implementation plausibly doesn't isolate that as cleanly as real POSIX fork+exec would. All three fixes (defer-to-next-turn, persistent event loop, stdin isolation) are kept regardless of which one(s) turn out to matter — each is independently a reasonable design regardless of this specific bug. Not yet re-tested on a real phone.
6. **Ordinary chat text triggered a completion dropdown on every keystroke — FIXED, 2026-07-19.** `FuzzyCompleter` matches a single typed character against any top-level command name by subsequence (e.g. "e" fuzzy-matches "/help", "/session", "/memory", ...), and `complete_while_typing=True` meant this fired on nearly every keystroke of plain chat text, not just slash commands. Fixed with `ui._SlashOnlyCompleter`, which only delegates to the real completer when the buffer starts with `/`. Not yet device-confirmed.
7. **Project detection silently regressed after a fresh clone — FIXED, 2026-07-19.** `PROJECT_MARKERS` didn't include `.git`, only `AGENTS.md`/`CLAUDE.md`/`.opencode`/`mobile_sessions`. When the a-cli repo itself is used as a project under `bookmark_root`, it was only recognized as a project once `mobile_sessions/` already existed there from a prior session — but that dir is gitignored, so a fresh `lg2 clone` lost the marker, project detection silently fell back to "no project," and `read_file`/`write_file`/`run_command` then resolved paths against `bookmark_root` instead of the actual project directory (symptom: the model couldn't find `README.md` even though it existed, and tried to `find` for it — which itself then hit issue #5's confirmation freeze). Fixed by adding `.git` to `PROJECT_MARKERS`, matching OpenCode's own convention and not depending on ephemeral, gitignored state.

## Verification approach

- **PC-testable** (`pytest`, no device needed): provider SSE/response parsing against recorded fixtures, live-model-list fallback behavior, slash-command parsing, skill/memory discovery, session store round-tripping and scoping, the mouse-toggle hook's logic in isolation (mocked `Buffer`/`Application`), secrets-isolation guard.
- **Device-only**: everything in Known Issues above, plus `~/Documents/bin` registration surviving app kill/reboot, real network behavior over WiFi/cellular, `bootstrap.sh` on a clean install, and general end-to-end usability.

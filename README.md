# a-cli

A small, LLM-agnostic agentic chat CLI built to run entirely on-device inside [a-shell](https://github.com/holzschu/a-shell), a non-jailbreak iOS terminal app. It gives you a real, usable chat/agent tool on your iPhone — with slash commands, skill files, and long-term project memory — without needing a jailbreak, a heavyweight Linux VM, or an always-on remote machine to SSH into.

## Motivation

Most "AI CLI on iOS" options fall into two buckets, and neither is great for daily use:

- **iSH** (a Linux syscall emulator) can run real Linux binaries, but it's slow, battery-hungry, and awkward for anything long-running.
- **SSH into a remote box** works, but it means either leaving your PC on all the time or paying for a cloud VM just so you can brainstorm from your phone.

a-cli takes a third path: it's a small pure-Python program that runs natively inside a-shell's own Python interpreter, talking directly to LLM APIs over HTTPS. No VM, no emulation, no server to keep alive. It's just a chat REPL you launch like any other a-shell command.

It's also deliberately **not tied to one AI vendor or one workflow**. The provider layer is a thin abstraction — add a new LLM provider by writing one small adapter file. And while it's genuinely useful as a standalone mobile chat tool on its own, it was designed so that if you *also* use an agentic coding CLI on your PC — [OpenCode](https://opencode.ai) is the one it was built around, but the same idea extends to Claude Code and similar tools — it can read and write the exact same on-disk conventions those tools already use:

- **Skills**: `.opencode/skills/<name>/SKILL.md` (with `.claude/skills/` and `.agents/skills/` recognized too)
- **Long-term memory**: plain `AGENTS.md` (falls back to `CLAUDE.md`)
- **Slash commands**: `.opencode/commands/<name>.md`

Point both tools at the same synced folder (OneDrive, iCloud Drive, Syncthing — anything that gives you a regular folder on both ends) and a skill or a memory note you write on your PC is immediately visible on your phone, and vice versa, with zero conversion step. That's a highlighted use case, not the only one — a-cli works fine pointed at a folder that OpenCode never touches, for general-purpose mobile AI chat, note-taking, or any other project-specific assistant.

## Features

- **LLM-agnostic**: ships with Anthropic and OpenAI providers behind a common interface; adding another provider doesn't touch the rest of the app.
- **Touch-friendly slash commands**: typing `/` pops up a filterable, tappable command list; `/model` and `/session` get their own contextual dropdowns.
- **Skills**: markdown skill files are discovered automatically; only their name and description are shown to the model up front, with full instructions loaded on demand — the same two-tier pattern OpenCode/Claude Code use.
- **Shared long-term memory**: reads project- and global-scoped `AGENTS.md`/`CLAUDE.md` files.
- **Agentic file/command access**: the model can read, write, and run commands in the current project (scoped to the project folder, never the wider filesystem) — writes and commands prompt you to confirm before they run.
- **Project-scoped and global sessions**: sessions created while you're "in" a project folder only show up there; sessions created at the top level of your shared folder are visible everywhere.
- **Secrets stay local**: API keys are never written into the synced folder — only to a local, device-only config path — so cloud-syncing your workflow folder never risks leaking a key.

## Requirements

- An iPhone or iPad with [a-shell](https://apps.apple.com/app/a-shell/id1473805438) installed (free, App Store).
- An API key for at least one supported provider (Anthropic and/or OpenAI).
- Optionally, a folder synced across devices (OneDrive, iCloud Drive, etc.) if you want shared skills/memory/sessions — a plain local folder works fine if you don't need that.

## Installation (inside a-shell)

1. **Clone the repo.** a-shell doesn't include full `git` — use its bundled `lg2` command (a lightweight libgit2-based git client) instead:

   ```sh
   lg2 clone https://github.com/dlcolby/a-cli.git ~/Documents/a-cli
   cd ~/Documents/a-cli
   ```

2. **Run the bootstrap script.** This installs the pure-Python dependencies (`requests`, `pyyaml`, `prompt_toolkit` — a-shell's `pip` can only build pure-Python packages, and everything this project depends on was chosen with that in mind), sets up a local, never-synced config directory at `~/Documents/.mobilecli/`, and drops a launcher at `~/Documents/bin/aic`. a-shell's shell is a POSIX `sh`, not `bash`, so run it with:

   ```sh
   sh bootstrap.sh
   ```

3. **(Optional) Set up your shared folder.** If you want skills/memory/sessions shared with a PC tool like OpenCode, use a-shell's `pickFolder` command to bookmark an **iCloud Drive** folder before continuing — `pickFolder` works cleanly for iCloud Drive. **OneDrive folders currently can't be selected this way**: OneDrive shows up as a location in the picker, but its folders never become selectable (a limitation of OneDrive's iOS Files-provider extension, not something fixable from a-shell). If you're committed to OneDrive, use a plain local a-shell folder as your workflow folder for now, and manually copy files in/out via the OneDrive app's "Save a copy"/"Export" — not automatic sync, but functional today. Direct OneDrive support without this limitation (via Microsoft's Graph API instead of the Files picker) is a planned but not-yet-built improvement.

4. **Run it:**

   ```sh
   aic
   ```

   On first run you'll be asked for:
   - An API key for your chosen provider (saved locally to `~/Documents/.mobilecli/secrets.json`, never into the shared folder).
   - The path to your shared workflow folder (the one you bookmarked in step 3, or any plain folder if you're not syncing).

5. Type `/help` to see available commands, or just start chatting.

## Usage

- Plain text sent at the prompt is a normal chat turn.
- The first exchange in a new session gets an automatic short title, proposed by a cheap/fast model (Haiku for Anthropic, GPT-5 mini for OpenAI) rather than whatever model you're actually chatting with — you'll see `[session auto-named: "..."]` after the first reply. Rename it any time with `/session rename <title>` (the session's timestamp-based id never changes).
- `/model [provider:alias]` — show or switch the active model (e.g. `/model openai:gpt5`), or `/model refresh` to re-query the live model list (see below). The `/model` dropdown only lists models for providers you've actually configured a key for, queried live from that provider's API — not a fixed guess — so it reflects what your key can actually access.
- `/session list|new [--global] [title]|switch <id>|rm <id>|rename <title>` — manage sessions. Without `--global`, a new session is scoped to the nearest project folder (one containing an `AGENTS.md`, `.opencode/`, or existing `mobile_sessions/`); with `--global`, it's visible from anywhere under your shared folder.
- `/skills` — list discovered skills.
- `/memory [append <text>]` — show loaded memory files, or quickly jot a note into the current project's `AGENTS.md`.
- `/mouse on|off` — toggle touch-tap completion selection vs. terminal scrollback. Both use the same underlying mouse-tracking mode, so only one works at a time: leave it on to tap-select from dropdowns, turn it off when you need to scroll back through chat history.
- `/exit` — save and quit.
- Any `.opencode/commands/<name>.md` file in your shared folder becomes available as `/<name>` automatically.

## Project layout

```
ai_cli/
  providers/        Provider abstraction + Anthropic/OpenAI adapters
  commands/         Built-in and markdown-file-defined slash commands
  config.py         Local secrets/config, kept out of the synced folder
  session.py        Project- vs global-scoped session storage
  memory.py         AGENTS.md / CLAUDE.md loading
  skills.py         Skill discovery + on-demand skill-body disclosure
  ui.py             prompt_toolkit-based touch-friendly input/completion
  repl.py           Main chat loop
bootstrap.sh         One-time installer, run inside a-shell
```

## Running the tests (on a PC)

The core logic (provider request/response parsing, session scoping, skill/memory discovery, slash-command parsing) has no iOS-specific dependencies and is tested with `pytest` on a regular machine:

```sh
pip install -r requirements.txt pytest
pytest
```

## Status / known limitations

This project is under active development. Confirmed working on-device (real iPhone, real a-shell):

- HTTPS networking from a-shell's Python interpreter, including genuinely incremental streamed responses (not buffered).
- `prompt_toolkit`'s completion dropdowns, including tapping a specific item out of several visible candidates to select it.

Known, currently unresolved:

- **OneDrive folders can't be selected via `pickFolder`** — see the installation section above. iCloud Drive works; OneDrive doesn't expose folder-level picking to other apps on iOS. Workaround: a local folder + manual "Save a copy"/"Export" for now. Real fix (Microsoft Graph API integration) is planned but not built.
- **Touch-select and terminal scrollback are mutually exclusive** — both rely on the same mouse-tracking terminal mode, so `/mouse on|off` lets you switch between them rather than having both simultaneously.

If you run into other rough edges, that's expected at this stage — issues and reports are welcome.

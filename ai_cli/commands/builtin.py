"""Built-in slash commands. Each takes (ctx, arg_string) and returns a string
to print to the user; some also mutate ctx (switching model/session, etc.)."""

from __future__ import annotations

from .. import memory, session as session_mod, skills as skills_mod
from ..providers.registry import PROVIDERS, create_provider, parse_model_ref


def cmd_help(ctx, args: str) -> str:
    lines = ["Built-in commands:"]
    for name, fn in BUILTINS.items():
        doc = (fn.__doc__ or "").strip().splitlines()[0] if fn.__doc__ else ""
        lines.append(f"  /{name} — {doc}")
    if ctx.markdown_commands:
        lines.append("")
        lines.append("Custom commands:")
        for name, cmd in ctx.markdown_commands.items():
            lines.append(f"  /{name} — {cmd.description}")
    return "\n".join(lines)


def cmd_model(ctx, args: str) -> str:
    """Show or switch the active model. Usage: /model [provider:model-or-alias] | /model refresh"""
    if not args.strip():
        return f"Current: {ctx.provider_name}:{ctx.model}"
    if args.strip() == "refresh":
        ctx.model_cache.clear()
        return "Model list cache cleared — it'll re-query on next /model dropdown."
    provider_name, model_ref = parse_model_ref(args.strip(), ctx.provider_name)
    if provider_name not in PROVIDERS:
        return f"Unknown provider '{provider_name}'. Available: {', '.join(PROVIDERS)}"
    api_key = ctx.get_api_key(provider_name)
    if not api_key:
        return f"No API key configured for '{provider_name}'. Set it via /setup or secrets.json."
    ctx.provider_name = provider_name
    ctx.provider = create_provider(provider_name, api_key)
    ctx.model = model_ref
    return f"Switched to {provider_name}:{model_ref}"


def cmd_provider(ctx, args: str) -> str:
    """List available providers, or switch the active one. Usage: /provider [name]"""
    if not args.strip():
        return f"Available: {', '.join(PROVIDERS)}. Current: {ctx.provider_name}"
    return cmd_model(ctx, args.strip() + ":" + ctx.config.default_model_alias)


def cmd_session(ctx, args: str) -> str:
    """Manage sessions. Usage: /session list|new [--global] [title]|switch <id>|rm <id>|rename <title>"""
    parts = args.split(maxsplit=1)
    sub = parts[0] if parts else "list"
    rest = parts[1] if len(parts) > 1 else ""

    if sub == "list":
        sessions = session_mod.list_sessions(ctx.cwd, ctx.bookmark_root)
        if not sessions:
            return "No sessions in scope."
        lines = []
        for s in sessions:
            marker = "*" if ctx.session and s["id"] == ctx.session.id else " "
            lines.append(f"{marker} [{s['scope']}] {s['id']} — {s['title']}")
        return "\n".join(lines)

    if sub == "new":
        global_scope = "--global" in rest
        title = rest.replace("--global", "").strip() or "untitled"
        ctx.session = session_mod.create_session(
            ctx.cwd, ctx.bookmark_root, ctx.provider_name, ctx.model, title=title, global_scope=global_scope
        )
        return f"Created {ctx.session.scope} session {ctx.session.id}"

    if sub == "switch":
        for s in session_mod.list_sessions(ctx.cwd, ctx.bookmark_root):
            if s["id"] == rest.strip() or s["id"].startswith(rest.strip()):
                ctx.session = session_mod.load_session(s["path"])
                return f"Switched to session {ctx.session.id}"
        return f"No in-scope session matching '{rest}'"

    if sub == "rm":
        for s in session_mod.list_sessions(ctx.cwd, ctx.bookmark_root):
            if s["id"] == rest.strip() or s["id"].startswith(rest.strip()):
                session_mod.delete_session(s["path"])
                return f"Deleted session {s['id']}"
        return f"No in-scope session matching '{rest}'"

    if sub == "rename":
        if not ctx.session:
            return "No active session to rename. Start chatting or /session new first."
        new_title = rest.strip()
        if not new_title:
            return "Usage: /session rename <new title>"
        ctx.session.title = new_title
        session_mod.save_session(ctx.session)
        return f"Renamed session to '{new_title}' (id unchanged: {ctx.session.id})"

    return f"Unknown /session subcommand '{sub}'"


def cmd_new(ctx, args: str) -> str:
    """Start a fresh session with the same provider/model. Usage: /new [title]"""
    return cmd_session(ctx, f"new {args}".strip())


def cmd_skills(ctx, args: str) -> str:
    """List discovered skills."""
    if not ctx.skills:
        return "No skills discovered."
    return "\n".join(f"[{s.scope}] {s.name} — {s.description}" for s in ctx.skills)


def cmd_memory(ctx, args: str) -> str:
    """Show loaded memory files, or append a note. Usage: /memory [append <text>]"""
    sub = args.strip()
    if sub.startswith("append "):
        note = sub[len("append "):]
        target_dir = ctx.project_dir or ctx.bookmark_root
        path = memory.append_note(target_dir, note)
        return f"Appended note to {path}"
    block = memory.load_memory_block(ctx.cwd, ctx.bookmark_root, ctx.project_dir)
    return block or "No memory files loaded (no AGENTS.md/CLAUDE.md found)."


def cmd_mouse(ctx, args: str) -> str:
    """Toggle touch-tap completion selection vs. terminal scrollback (can't have
    both at once — mouse mode captures scroll gestures). Usage: /mouse on|off"""
    choice = args.strip().lower()
    if choice not in ("on", "off"):
        state = "on" if ctx.mouse_enabled else "off"
        return f"Usage: /mouse on|off (currently {state})"
    ctx.mouse_enabled = choice == "on"
    if ctx.mouse_enabled:
        return "Mouse mode on: tap to select completions; scrollback won't work until you turn it off."
    return "Mouse mode off: scrollback restored; use arrow keys to select completions."


def cmd_exit(ctx, args: str) -> str:
    """Save the current session and exit."""
    if ctx.session:
        session_mod.save_session(ctx.session)
    ctx.should_exit = True
    return "Goodbye."


BUILTINS = {
    "help": cmd_help,
    "model": cmd_model,
    "provider": cmd_provider,
    "session": cmd_session,
    "new": cmd_new,
    "skills": cmd_skills,
    "memory": cmd_memory,
    "mouse": cmd_mouse,
    "exit": cmd_exit,
}

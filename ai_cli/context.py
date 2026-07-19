"""Shared mutable app state passed to command handlers and the REPL loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import config as config_mod
from .providers.base import Provider
from .session import Session


@dataclass
class AppContext:
    config: config_mod.Config
    cwd: Path
    bookmark_root: Path
    project_dir: Optional[Path]
    provider_name: str
    provider: Provider
    model: str
    session: Optional[Session] = None
    skills: list = field(default_factory=list)
    markdown_commands: dict = field(default_factory=dict)
    should_exit: bool = False
    model_cache: dict = field(default_factory=dict)  # provider_name -> list[ModelInfo], live-queried
    mouse_mode: str = "auto"  # "auto" | "on" | "off" — see ui.py docstring
    repl_ui: Optional[object] = None  # ui.Repl_UI once main() constructs it; None in tests/no-UI contexts

    def get_api_key(self, provider_name: str) -> Optional[str]:
        return config_mod.get_api_key(provider_name)

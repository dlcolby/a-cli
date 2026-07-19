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

    def get_api_key(self, provider_name: str) -> Optional[str]:
        return config_mod.get_api_key(provider_name)

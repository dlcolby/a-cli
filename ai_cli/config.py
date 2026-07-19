"""Local (never-synced) config + secrets handling.

Secrets precedence: env var > secrets.json > interactive first-run prompt.
Everything here lives under LOCAL_HOME (~/Documents/.mobilecli by default,
overridable via MOBILECLI_HOME for PC testing) — never under bookmark_root,
which is the OneDrive-synced folder shared with OpenCode on PC.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

ENV_VAR_BY_PROVIDER = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def local_home() -> Path:
    override = os.environ.get("MOBILECLI_HOME")
    if override:
        return Path(override)
    return Path.home() / "Documents" / ".mobilecli"


def config_path() -> Path:
    return local_home() / "config.json"


def secrets_path() -> Path:
    return local_home() / "secrets.json"


@dataclass
class Config:
    bookmark_root: Optional[str] = None
    global_workflow_dir: Optional[str] = None
    default_provider: str = "anthropic"
    default_model_alias: str = "sonnet"
    stream: bool = True

    @classmethod
    def load(cls) -> "Config":
        path = config_path()
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def save(self) -> None:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "bookmark_root": self.bookmark_root,
                    "global_workflow_dir": self.global_workflow_dir,
                    "default_provider": self.default_provider,
                    "default_model_alias": self.default_model_alias,
                    "stream": self.stream,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def assert_secrets_isolated(self) -> None:
        """Guard against secrets ever living inside the synced bookmark tree."""
        if not self.bookmark_root:
            return
        bookmark = Path(self.bookmark_root).resolve()
        secrets = secrets_path().resolve()
        if bookmark == secrets or bookmark in secrets.parents:
            raise RuntimeError(
                f"Refusing to proceed: secrets path {secrets} is inside bookmark_root "
                f"{bookmark}. Secrets must never live in the OneDrive-synced tree."
            )


def load_secrets() -> dict:
    path = secrets_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_secrets(secrets: dict) -> None:
    path = secrets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(secrets, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # best-effort; not all filesystems (e.g. some iOS providers) support chmod


def get_api_key(provider: str) -> Optional[str]:
    env_var = ENV_VAR_BY_PROVIDER.get(provider)
    if env_var and os.environ.get(env_var):
        return os.environ[env_var]
    secrets = load_secrets()
    return secrets.get(f"{provider}_api_key")

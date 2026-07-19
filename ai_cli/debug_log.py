"""Opt-in diagnostic logging for on-device debugging.

a-shell crashes/freezes can't be attached to with a real debugger, and some
of them (silent app-close, hard freeze) leave no traceback at all — so this
exists purely to leave a paper trail that survives on disk even when the
process never gets to shut down cleanly. Each call opens, writes, and closes
the file immediately (no buffering to lose), so whatever was logged right up
to the moment of a freeze/crash is still there to read afterward.

No-op unless AIC_DEBUG_LOG is set to a file path, so this costs nothing and
changes nothing in normal use.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone


def log(message: str) -> None:
    path = os.environ.get("AIC_DEBUG_LOG")
    if not path:
        return
    line = f"{datetime.now(timezone.utc).isoformat()} {message}\n"
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass  # logging itself must never be what crashes the app

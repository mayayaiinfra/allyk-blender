# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 MAYAYAI
"""A small local error log: one JSON line per failure in Blender's user config folder.

Each line holds the UTC time, a fixed boundary name, the exception class and a
typed code. Never a key, token, pairing code, message text, file or scene path.
The file is rotated at 256 KB and one older file is kept, so it stays under
512 KB. Writing the log never raises; the typed message the user sees in the
panel is unchanged.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

import bpy

MAX_BYTES = 256 * 1024
_NAME = re.compile(r"[a-z_][a-z0-9_.]{0,63}")
_CLASS = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_lock = threading.Lock()
_folder: Path | None = None


def _path() -> Path:
    global _folder
    if _folder is None:
        # Resolved once on the main thread (register) so the network thread never calls bpy.
        _folder = Path(bpy.utils.user_resource("CONFIG", path="allyk_for_blender", create=True))
    return _folder / "errors.jsonl"


def prepare() -> None:
    """Called from register(); resolves the folder on Blender's main thread."""
    try:
        _path()
    except (OSError, RuntimeError, ValueError):
        _disable()


def _disable() -> None:
    global _folder
    _folder = Path()  # An empty folder name: record() skips writing when it cannot be resolved.


def record(boundary: str, error: BaseException | None, code: str) -> None:
    """Append one line; any failure of the log itself is dropped."""
    line = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "boundary": boundary if _NAME.fullmatch(boundary) else "unknown",
        "exception": type(error).__name__ if error is not None and _CLASS.fullmatch(type(error).__name__) else "None",
        "code": code if isinstance(code, str) and _NAME.fullmatch(code) else "unknown",
    }
    try:
        with _lock:
            path = _path()
            if path.parent == Path():
                return
            if path.exists() and path.stat().st_size >= MAX_BYTES:
                path.replace(path.with_name("errors.1.jsonl"))
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(line, separators=(",", ":")) + "\n")
    except (OSError, RuntimeError, ValueError):
        return  # The log is best effort: a full disk or locked file must not break the add-on.

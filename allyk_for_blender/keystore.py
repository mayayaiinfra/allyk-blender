# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 MAYAYAI
"""The device key and the user's offered files, kept in Blender's user config folder.

Never in a .blend file, a scene or a log. The key file is made readable by the
current operating-system user only where the platform allows it.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from pathlib import Path

import bpy

_FOLDER = "allyk_for_blender"


def _folder() -> Path:
    path = Path(bpy.utils.user_resource("CONFIG", path=_FOLDER, create=True))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_private(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def new_key() -> dict:
    """A fresh key: allyk_dev_ + 43 base64url characters (32 random bytes)."""
    key = "allyk_dev_" + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")
    return {"key": key, "key_prefix": key[:18], "key_hash": "sha256:" + hashlib.sha256(key.encode("utf-8")).hexdigest()}


def load_state() -> dict:
    return _read(_folder() / "device.json")


def save_state(state: dict) -> None:
    _write_private(_folder() / "device.json", state)


def forget() -> None:
    for name in ("device.json",):
        try:
            (_folder() / name).unlink()
        except FileNotFoundError:
            pass


def load_assets() -> dict:
    return _read(_folder() / "assets.json")


def offer_asset(path: str) -> str:
    """Make one user-chosen glTF/GLB file available to ALLYK; returns its token."""
    assets = load_assets()
    token = secrets.token_urlsafe(18)
    fmt = "glb" if path.lower().endswith(".glb") else "gltf"
    assets[token] = {"path": path, "format": fmt, "label": os.path.basename(path)[:120]}
    _write_private(_folder() / "assets.json", assets)
    return token


def withdraw_asset(token: str) -> None:
    assets = load_assets()
    assets.pop(token, None)
    _write_private(_folder() / "assets.json", assets)

# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 MAYAYAI
"""HTTPS client for the Design Bridge API (docs/DESIGN_PUBLIC_API.md in ALLYK).

Outbound requests only; nothing here listens on a port. The device key is sent
as the bearer credential after pairing; during pairing only its hash is sent.
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request

from . import errorlog

DEFAULT_BASE_URL = "https://allyk.app/api/native/design"
TIMEOUT_SECONDS = 20


class ApiError(Exception):
    """A refused or failed call; `code` is the documented error code."""

    def __init__(self, status: int, code: str, body: dict | None = None):
        self.status, self.code, self.body = status, code, body or {}
        super().__init__(f"{status} {code}")


def _context() -> ssl.SSLContext:
    return ssl.create_default_context()


def call(base_url: str, method: str, path: str, body: dict | None = None, key: str | None = None) -> dict:
    url = base_url.rstrip("/") + path
    if not (url.startswith("https://") or url.startswith("http://localhost") or url.startswith("http://127.0.0.1")):
        raise ApiError(0, "insecure_url")
    headers = {"accept": "application/json", "x-allyk-client-version": "allyk-for-blender/0.1.2"}
    data = None
    if body is not None:
        data = json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers["content-type"] = "application/json"
    if key:
        headers["authorization"] = f"Bearer {key}"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS, context=_context() if url.startswith("https") else None) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as error:
        try:
            payload = json.loads(error.read().decode("utf-8") or "{}")
        except ValueError as parse_error:
            errorlog.record("api.response", parse_error, "error_body_unreadable")
            payload = {}
        raise ApiError(error.code, str(payload.get("error") or "unavailable"), payload) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ApiError(0, "unavailable") from None


def start_pairing(base_url: str, key_prefix: str, key_hash: str, client_version: str, platform: str) -> dict:
    return call(base_url, "POST", "/pairing", {"key_prefix": key_prefix, "key_hash": key_hash,
                                              "client_version": client_version, "platform": platform})


def pairing_status(base_url: str, pairing_id: str, key_hash: str) -> dict:
    return call(base_url, "POST", "/pairing/status", {"pairing_id": pairing_id, "key_hash": key_hash})


def send_snapshot(base_url: str, key: str, snapshot: dict) -> dict:
    return call(base_url, "POST", "/v1/snapshots", snapshot, key)


def claim(base_url: str, key: str, connect_id: str = "blender") -> dict:
    return call(base_url, "POST", "/v1/commands/claim", {"connect_id": connect_id}, key)


def send_result(base_url: str, key: str, command_id: str, result: dict) -> dict:
    return call(base_url, "POST", f"/v1/commands/{command_id}/result", result, key)

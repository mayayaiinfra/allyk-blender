# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 MAYAYAI
"""Pairing and the command loop (DESIGN_PUBLIC_API.md sections 3 to 5).

Network calls run on one background thread so Blender stays responsive;
commands are applied only on Blender's main thread, from a timer. While the
user has the connection switched on, the add-on claims work no more often than
every 5 seconds. Each command_id is applied at most once; its stored result is
re-sent instead of applying it again.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import queue
import threading
import time
from pathlib import Path

import bpy

from . import api, commands, keystore, snapshot

CLIENT_VERSION = "0.1.0"
CLAIM_INTERVAL = 5.0

state = {"status": "not_paired", "message": "", "user_code": "", "verification_uri": "", "connected": False,
         "busy": False, "last_claim": 0.0, "poll_interval": 5.0, "last_poll": 0.0}
_jobs: "queue.Queue[tuple]" = queue.Queue()
_main: "queue.Queue[tuple]" = queue.Queue()


def _prefs():
    return bpy.context.preferences.addons[__package__].preferences


def _base_url() -> str:
    return (_prefs().base_url or api.DEFAULT_BASE_URL).strip()


def _platform() -> str:
    system = {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}.get(platform.system(), "other")
    machine = (platform.machine() or "x64").lower().replace("amd64", "x64").replace("x86_64", "x64")
    return f"{system}-{machine}"[:80]


def _applied_path() -> Path:
    return Path(bpy.utils.user_resource("CONFIG", path="allyk_for_blender", create=True)) / "applied.json"


def _applied() -> dict:
    try:
        return json.loads(_applied_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _remember(run_id: str, command_id: str, result: dict) -> None:
    data = _applied()
    data.setdefault(run_id, {})[command_id] = result
    _applied_path().write_text(json.dumps(data), encoding="utf-8")


def _forget_run(run_id: str) -> None:
    data = _applied()
    if data.pop(run_id, None) is not None:
        _applied_path().write_text(json.dumps(data), encoding="utf-8")


def _worker():
    while True:
        job, payload = _jobs.get()
        try:
            _main.put((job, payload, job_call(job, payload), None))
        except api.ApiError as error:
            _main.put((job, payload, None, error))


def job_call(job, payload):
    base = _base_url()
    if job == "pair":
        return api.start_pairing(base, payload["key_prefix"], payload["key_hash"], CLIENT_VERSION, _platform())
    if job == "poll":
        return api.pairing_status(base, payload["pairing_id"], payload["key_hash"])
    if job == "snapshot":
        return api.send_snapshot(base, payload["key"], payload["snapshot"])
    if job == "claim":
        return api.claim(base, payload["key"])
    if job == "results":
        sent = []
        for command_id, result in payload["results"]:
            sent.append(api.send_result(base, payload["key"], command_id, result))
        return sent
    raise ValueError(job)


_thread = threading.Thread(target=_worker, name="allyk-for-blender", daemon=True)


def ensure_worker():
    if not _thread.is_alive():
        _thread.start()


# ---- user actions -----------------------------------------------------------

def start_pairing():
    material = keystore.new_key()
    keystore.save_state({"key": material["key"], "key_prefix": material["key_prefix"], "key_hash": material["key_hash"],
                         "linked": False})
    state.update(status="pairing", message="Asking ALLYK for a code...", user_code="", busy=True)
    _jobs.put(("pair", material))


def unpair():
    keystore.forget()
    state.update(status="not_paired", connected=False, user_code="", message="This device is no longer paired.")


def send_snapshot(character_object=None):
    device = keystore.load_state()
    if not device.get("linked"):
        state["message"] = "Pair with ALLYK first."
        return
    _jobs.put(("snapshot", {"key": device["key"], "snapshot": snapshot.build(keystore.load_assets(), character_object)}))


# ---- main-thread timer ------------------------------------------------------

def _handle(job, payload, result, error):
    if error is not None:
        if error.status == 401:
            keystore.forget()
            state.update(status="not_paired", connected=False, busy=False,
                         message="ALLYK no longer accepts this device (revoked or unknown). Pair again.")
            return
        if job == "poll" and error.code == "slow_down":
            state["poll_interval"] = float(error.body.get("interval") or state["poll_interval"] + 5)
            return
        state.update(busy=False, message=f"ALLYK: {error.code}")
        if job == "pair":
            state["status"] = "not_paired"
        return
    if job == "pair":
        device = keystore.load_state()
        device["pairing_id"] = result["pairing_id"]
        keystore.save_state(device)
        state.update(status="waiting_for_user", user_code=result["user_code"], verification_uri=result["verification_uri"],
                     poll_interval=float(result.get("interval", 5)), busy=False,
                     message="Type this code at the address below, signed in to ALLYK.")
    elif job == "poll":
        status = result.get("status")
        if status == "linked":
            device = keystore.load_state()
            device["linked"] = True
            device.pop("pairing_id", None)
            keystore.save_state(device)
            state.update(status="paired", user_code="", message="Paired with ALLYK.")
            send_snapshot()
        elif status in ("denied", "expired"):
            keystore.forget()
            state.update(status="not_paired", user_code="", message=f"Pairing {status}. Start again if you want to pair.")
    elif job == "snapshot":
        state["message"] = "Scene summary sent to ALLYK."
    elif job == "claim":
        state["busy"] = False
        run = result.get("run")
        if run:
            _apply_run(run)
        elif result.get("waiting_for_approval"):
            state["message"] = "A run is waiting for your approval in ALLYK."
    elif job == "results":
        run_id = payload["run_id"]
        if payload.get("finished"):
            _forget_run(run_id)
            send_snapshot()
        state["busy"] = False


def _apply_run(run):
    device = keystore.load_state()
    prefs = _prefs()
    run_id = run["run_id"]
    done = _applied().get(run_id, {})
    results = []
    for index, command in enumerate(sorted(run["commands"], key=lambda item: item["sequence"])):
        command_id = command["command_id"]
        if command_id in done:
            results.append((command_id, done[command_id]))
            continue
        try:
            if index == 0 and not done and command.get("planned_revision") != snapshot.scene_revision():
                raise commands.Refused("stale_revision", "The scene changed since ALLYK planned this run.")
            name, params = commands.validate(command)
            outputs = commands.apply(name, params, keystore.load_assets(), prefs.output_folder, run_id)
            result = {"protocol_version": commands.PROTOCOL, "command_id": command_id, "status": "done",
                      "new_revision": snapshot.scene_revision(),
                      "outputs": [_fingerprint(item) for item in outputs]}
        except commands.Refused as refusal:
            result = {"protocol_version": commands.PROTOCOL, "command_id": command_id, "status": "refused",
                      "reason": refusal.reason, "new_revision": snapshot.scene_revision()}
            if refusal.message:
                result["message"] = refusal.message
        except Exception:  # Blender raised: report a failure, never the exception text (it may hold paths).
            result = {"protocol_version": commands.PROTOCOL, "command_id": command_id, "status": "failed",
                      "reason": "application_error", "new_revision": snapshot.scene_revision()}
        _remember(run_id, command_id, result)
        results.append((command_id, result))
        if result["status"] != "done":
            break  # A refused or failed command ends the run; nothing later is applied.
    state.update(busy=True, message=f"Applied {len(results)} command(s); reporting to ALLYK.")
    # The stored results are cleared only after ALLYK has accepted them.
    _jobs.put(("results", {"key": device["key"], "results": results, "run_id": run_id, "finished": True}))


def _fingerprint(item):
    digest = hashlib.sha256()
    with open(item["path"], "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return {"kind": item["kind"], "sha256": digest.hexdigest(), "bytes": os.path.getsize(item["path"])}


def tick():
    """Runs on Blender's main thread every second while the add-on is enabled."""
    while not _main.empty():
        _handle(*_main.get_nowait())
    now = time.monotonic()
    device = keystore.load_state()
    if state["status"] == "waiting_for_user" and device.get("pairing_id") and now - state["last_poll"] >= state["poll_interval"]:
        state["last_poll"] = now
        _jobs.put(("poll", {"pairing_id": device["pairing_id"], "key_hash": device["key_hash"]}))
    if device.get("linked") and state["status"] != "paired":
        state["status"] = "paired"
    if state["connected"] and device.get("linked") and not state["busy"] and now - state["last_claim"] >= CLAIM_INTERVAL:
        state.update(last_claim=now, busy=True)
        _jobs.put(("claim", {"key": device["key"]}))
    return 1.0

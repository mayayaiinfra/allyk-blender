# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 MAYAYAI
"""Minimized scene snapshot and scene revision (DESIGN_PUBLIC_API.md sections 4.1 and 5).

Only object names, types and counts, the files the user offered, and, when the
user asks for a character check, a summary of the selected character. Never
geometry, material content, textures, paths or files.
"""
from __future__ import annotations

import hashlib
import json
import math
import uuid

import bmesh
import bpy

PROTOCOL = "allyk.design.command.v1"
_TYPES = {"MESH": "mesh", "ARMATURE": "armature", "CAMERA": "camera", "LIGHT": "light", "EMPTY": "empty", "CURVE": "curve"}


def _round(values):
    return [round(float(value), 4) for value in values]


def scene_revision(scene=None) -> str:
    """SHA-256 of [name, type, location, rotation in degrees, scale, material names] for every object, sorted by name."""
    scene = scene or bpy.context.scene
    rows = []
    for obj in sorted(scene.objects, key=lambda item: item.name):
        materials = [slot.material.name for slot in obj.material_slots if slot.material] if obj.type == "MESH" else []
        rows.append([obj.name, obj.type, _round(obj.location), _round(math.degrees(v) for v in obj.rotation_euler),
                     _round(obj.scale), materials])
    canonical = json.dumps(rows, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _objects(scene):
    items = []
    for obj in list(scene.objects)[:2000]:
        if len(obj.name) > 120:
            continue
        item = {"ref": obj.name, "type": _TYPES.get(obj.type, "other"), "selected": bool(obj.select_get())}
        if obj.type == "MESH":
            item["vertex_count"] = len(obj.data.vertices)
            item["material_count"] = len([slot for slot in obj.material_slots if slot.material])
        items.append(item)
    return items


def _armature(obj):
    if obj.parent is not None and obj.parent.type == "ARMATURE":
        return obj.parent
    for modifier in obj.modifiers:
        if modifier.type == "ARMATURE" and modifier.object is not None:
            return modifier.object
    return None


def _names(values, limit=512):
    return [name for name in values if 0 < len(name) <= 120][:limit]


def character_summary(obj) -> dict:
    """The selected mesh character, minimized for Character Consistency."""
    scene = bpy.context.scene
    armature = _armature(obj)
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        topology = {"non_manifold_edges": sum(1 for edge in bm.edges if not edge.is_manifold),
                    "loose_vertices": sum(1 for vertex in bm.verts if not vertex.link_edges),
                    "ngons": sum(1 for face in bm.faces if len(face.verts) > 4)}
    finally:
        bm.free()
    keys = obj.data.shape_keys.key_blocks if obj.data.shape_keys else []
    return {
        "object_ref": obj.name,
        "scale": _round(obj.scale),
        "scene_units": {"system": scene.unit_settings.system, "scale_length": float(scene.unit_settings.scale_length)},
        "collections": _names(collection.name for collection in obj.users_collection),
        "scene_collections": _names(collection.name for collection in bpy.data.collections),
        "uv_layer_count": min(len(obj.data.uv_layers), 64),
        "materials": _names((slot.material.name for slot in obj.material_slots if slot.material), 128),
        "vertex_groups": _names(group.name for group in obj.vertex_groups),
        "shape_keys": _names(key.name for key in keys),
        "armature_ref": armature.name if armature is not None and len(armature.name) <= 120 else None,
        "bones": _names(bone.name for bone in armature.data.bones) if armature is not None else [],
        "topology": topology,
    }


def build(assets: dict, character_object=None) -> dict:
    scene = bpy.context.scene
    snapshot = {
        "protocol_version": PROTOCOL,
        "operation_id": str(uuid.uuid4()),
        "connect_id": "blender",
        "application_version": bpy.app.version_string[:40],
        "scene_revision": scene_revision(scene),
        "objects": _objects(scene),
        "assets": [{"path_token": token, "format": item["format"], "label": item["label"]}
                   for token, item in list(assets.items())[:200]],
    }
    if character_object is not None and character_object.type == "MESH":
        snapshot["character"] = character_summary(character_object)
    return snapshot

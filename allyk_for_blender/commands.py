# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 MAYAYAI
"""Validate and apply allyk.design.command.v1 commands (DESIGN_PUBLIC_API.md sections 5 and 6).

Every command is checked against its published parameters before the scene is
touched. Each command runs fixed code; nothing received from ALLYK is ever
evaluated, executed, imported, or used as an operator name.
"""
from __future__ import annotations

import math
import os
import re

import bpy

PROTOCOL = "allyk.design.command.v1"
_REF = re.compile(r"^[^\x00-\x1f\\/]{1,120}$")
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


class Refused(Exception):
    """A command the Design Connect will not apply; `reason` is the documented code."""

    def __init__(self, reason: str, message: str = ""):
        self.reason, self.message = reason, message[:300]
        super().__init__(reason)


# ---- parameter checks -------------------------------------------------------

def _ref(value):
    if not isinstance(value, str) or not _REF.match(value):
        raise Refused("invalid_params")
    return value


def _num(value, low, high, *, exclusive_low=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise Refused("invalid_params")
    if value > high or value < low or (exclusive_low and value <= low):
        raise Refused("invalid_params")
    return float(value)


def _int(value, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise Refused("invalid_params")
    return value


def _vec(value, size, low, high):
    if not isinstance(value, list) or len(value) != size:
        raise Refused("invalid_params")
    return [_num(item, low, high) for item in value]


def _enum(value, allowed):
    if value not in allowed:
        raise Refused("invalid_params")
    return value


def _token(value):
    if not isinstance(value, str) or not _TOKEN.match(value):
        raise Refused("invalid_params")
    return value


def _refs(value):
    if not isinstance(value, list) or len(value) > 200:
        raise Refused("invalid_params")
    return [_ref(item) for item in value]


def _resolution(value):
    if not isinstance(value, dict) or set(value) != {"width", "height"}:
        raise Refused("invalid_params")
    return {"width": _int(value["width"], 16, 7680), "height": _int(value["height"], 16, 4320)}


# name: (required, optional, field checks)
_SPEC = {
    "scene.import_asset": ({"path_token", "format"}, {"object_ref"}, {
        "path_token": _token,
        "format": lambda v: _enum(v, {"glb", "gltf"}),
        "object_ref": _ref}),
    "scene.set_transform": ({"object_ref"}, {"location", "rotation_deg", "scale"}, {
        "object_ref": _ref, "location": lambda v: _vec(v, 3, -100000, 100000),
        "rotation_deg": lambda v: _vec(v, 3, -360, 360), "scale": lambda v: _vec(v, 3, 0.0001, 10000)}),
    "scene.set_camera": ({"camera_ref", "location", "rotation_deg"}, {"focal_length_mm"}, {
        "camera_ref": _ref, "location": lambda v: _vec(v, 3, -100000, 100000),
        "rotation_deg": lambda v: _vec(v, 3, -360, 360), "focal_length_mm": lambda v: _num(v, 1, 1000)}),
    "scene.set_light": ({"light_ref", "kind", "location"}, {"rotation_deg", "energy_w", "color"}, {
        "light_ref": _ref, "kind": lambda v: _enum(v, {"point", "sun", "area", "spot"}),
        "location": lambda v: _vec(v, 3, -100000, 100000), "rotation_deg": lambda v: _vec(v, 3, -360, 360),
        "energy_w": lambda v: _num(v, 0, 1000000), "color": lambda v: _vec(v, 3, 0, 1)}),
    "scene.set_material": ({"object_ref"}, {"base_color", "metallic", "roughness"}, {
        "object_ref": _ref, "base_color": lambda v: _vec(v, 4, 0, 1),
        "metallic": lambda v: _num(v, 0, 1), "roughness": lambda v: _num(v, 0, 1)}),
    "render.still": ({"camera_ref", "resolution"}, {"samples"}, {
        "camera_ref": _ref, "resolution": _resolution, "samples": lambda v: _int(v, 1, 4096)}),
    "render.turntable": ({"camera_ref", "resolution", "frames"}, {"samples"}, {
        "camera_ref": _ref, "resolution": _resolution, "frames": lambda v: _int(v, 2, 720),
        "samples": lambda v: _int(v, 1, 4096)}),
    "export.gltf": ({"selection", "format"}, {"object_refs"}, {
        "selection": lambda v: _enum(v, {"all", "selected", "objects"}), "format": lambda v: _enum(v, {"glb", "gltf"}),
        "object_refs": _refs}),
    "scene.apply_scale": ({"object_ref"}, set(), {"object_ref": _ref}),
    "scene.rename_object": ({"object_ref", "new_name"}, set(), {"object_ref": _ref, "new_name": _ref}),
    "scene.ensure_collection": ({"collection_ref"}, set(), {"collection_ref": _ref}),
    "scene.link_to_collection": ({"object_ref", "collection_ref"}, set(), {"object_ref": _ref, "collection_ref": _ref}),
    "scene.set_units": ({"system", "scale_length"}, set(), {
        "system": lambda v: _enum(v, {"NONE", "METRIC", "IMPERIAL"}),
        "scale_length": lambda v: _num(v, 0, 10000, exclusive_low=True)}),
}


def validate(command: dict) -> tuple[str, dict]:
    """Return (name, params) or raise Refused before anything is applied."""
    name = command.get("command")
    if command.get("protocol_version") != PROTOCOL or name not in _SPEC:
        raise Refused("unknown_command")
    params = command.get("params")
    required, optional, checks = _SPEC[name]
    if not isinstance(params, dict) or not required <= set(params) or set(params) - required - optional:
        raise Refused("invalid_params")
    checked = {key: checks[key](value) for key, value in params.items()}
    if name == "export.gltf" and (checked["selection"] == "objects") != bool(checked.get("object_refs")):
        raise Refused("invalid_params")
    return name, checked


# ---- application ------------------------------------------------------------

def _object(ref):
    obj = bpy.data.objects.get(ref)
    if obj is None:
        raise Refused("unknown_ref", "No object with that name in this scene.")
    return obj


def _radians(values):
    return [math.radians(value) for value in values]


def _named(ref, kind):
    """The named camera or light, created when it does not exist (spec section 5, item 5)."""
    obj = bpy.data.objects.get(ref)
    if obj is not None:
        if obj.type != kind:
            raise Refused("unknown_ref", f"'{ref}' exists but is not a {kind.lower()}.")
        return obj
    data = bpy.data.cameras.new(ref) if kind == "CAMERA" else bpy.data.lights.new(ref, "POINT")
    obj = bpy.data.objects.new(ref, data)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _name_import_root(added, root_name, scene):
    """Give what one import added a single name (section 6): one top-level object is renamed;
    several are parented, keeping their world placement, to a new empty with that name."""
    tops = [obj for obj in added if obj.parent not in added]
    if len(tops) == 1:
        tops[0].name = root_name
        return
    root = bpy.data.objects.new(root_name, None)
    scene.collection.objects.link(root)
    for obj in tops:
        placement = obj.matrix_world.copy()
        obj.parent = root
        obj.matrix_world = placement


def _output_path(folder: str, name: str) -> str:
    if not folder or not os.path.isdir(folder):
        raise Refused("application_error", "Choose an output folder in ALLYK for Blender's preferences.")
    return os.path.join(folder, name)


def _set_samples(scene, samples):
    if samples is None:
        return
    if scene.render.engine == "CYCLES":
        scene.cycles.samples = samples
    elif hasattr(scene, "eevee"):
        scene.eevee.taa_render_samples = samples


def _render(scene, camera, resolution, samples, path):
    scene.camera = camera
    scene.render.resolution_x, scene.render.resolution_y = resolution["width"], resolution["height"]
    scene.render.resolution_percentage = 100
    _set_samples(scene, samples)
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


def apply(name: str, params: dict, assets: dict, output_folder: str, run_id: str) -> list[dict]:
    """Apply one validated command; returns output descriptors (path, kind) for fingerprinting."""
    scene = bpy.context.scene
    if name == "scene.import_asset":
        asset = assets.get(params["path_token"])
        if not asset or not os.path.isfile(asset["path"]):
            raise Refused("unknown_path_token")
        root_name = params.get("object_ref")
        if root_name is not None and bpy.data.objects.get(root_name) is not None:
            raise Refused("application_error", "Another object already has that name.")
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=asset["path"])
        if root_name is not None:
            _name_import_root([obj for obj in bpy.data.objects if obj not in before], root_name, scene)
    elif name == "scene.set_transform":
        obj = _object(params["object_ref"])
        if "location" in params:
            obj.location = params["location"]
        if "rotation_deg" in params:
            obj.rotation_euler = _radians(params["rotation_deg"])
        if "scale" in params:
            obj.scale = params["scale"]
    elif name in ("scene.set_camera", "scene.set_light"):
        kind = "CAMERA" if name == "scene.set_camera" else "LIGHT"
        obj = _named(params["camera_ref" if kind == "CAMERA" else "light_ref"], kind)
        obj.location = params["location"]
        if "rotation_deg" in params:
            obj.rotation_euler = _radians(params["rotation_deg"])
        if kind == "CAMERA" and "focal_length_mm" in params:
            obj.data.lens = params["focal_length_mm"]
        if kind == "LIGHT":
            obj.data.type = params["kind"].upper()
            if "energy_w" in params:
                obj.data.energy = params["energy_w"]
            if "color" in params:
                obj.data.color = params["color"]
    elif name == "scene.set_material":
        obj = _object(params["object_ref"])
        if obj.type != "MESH":
            raise Refused("unknown_ref", "Materials can be set on mesh objects only.")
        material = obj.active_material
        if material is None:
            material = bpy.data.materials.new(f"{obj.name}_Material")
            obj.data.materials.append(material)
        material.use_nodes = True
        bsdf = next((node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"), None)
        if bsdf is None:
            raise Refused("application_error", "The material has no Principled BSDF node.")
        if "base_color" in params:
            bsdf.inputs["Base Color"].default_value = params["base_color"]
        if "metallic" in params:
            bsdf.inputs["Metallic"].default_value = params["metallic"]
        if "roughness" in params:
            bsdf.inputs["Roughness"].default_value = params["roughness"]
    elif name == "render.still":
        camera = _object(params["camera_ref"])
        path = _output_path(output_folder, f"allyk_{run_id[:8]}_still.png")
        _render(scene, camera, params["resolution"], params.get("samples"), path)
        return [{"path": path, "kind": "render_image"}]
    elif name == "render.turntable":
        camera = _object(params["camera_ref"])
        pivot = bpy.data.objects.new("ALLYK_Turntable_Pivot", None)
        scene.collection.objects.link(pivot)
        old_parent, old_matrix = camera.parent, camera.matrix_world.copy()
        camera.parent = pivot
        camera.matrix_parent_inverse = pivot.matrix_world.inverted()
        outputs = []
        try:
            for frame in range(params["frames"]):
                pivot.rotation_euler = (0.0, 0.0, 2 * math.pi * frame / params["frames"])
                bpy.context.view_layer.update()
                path = _output_path(output_folder, f"allyk_{run_id[:8]}_turntable_{frame:04d}.png")
                _render(scene, camera, params["resolution"], params.get("samples"), path)
                outputs.append({"path": path, "kind": "render_frame"})
        finally:
            camera.parent = old_parent
            camera.matrix_world = old_matrix
            bpy.data.objects.remove(pivot)
        return outputs
    elif name == "export.gltf":
        suffix = "glb" if params["format"] == "glb" else "gltf"
        path = _output_path(output_folder, f"allyk_{run_id[:8]}_export.{suffix}")
        selection = params["selection"]
        if selection == "objects":
            for obj in scene.objects:
                obj.select_set(False)
            for ref in params["object_refs"]:
                _object(ref).select_set(True)
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB" if suffix == "glb" else "GLTF_SEPARATE",
                                  use_selection=selection != "all")
        return [{"path": path, "kind": "export_file"}]
    elif name == "scene.apply_scale":
        obj = _object(params["object_ref"])
        with bpy.context.temp_override(active_object=obj, object=obj, selected_editable_objects=[obj], selected_objects=[obj]):
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    elif name == "scene.rename_object":
        obj = _object(params["object_ref"])
        if bpy.data.objects.get(params["new_name"]) not in (None, obj):
            raise Refused("application_error", "Another object already has that name.")
        obj.name = params["new_name"]
    elif name == "scene.ensure_collection":
        if bpy.data.collections.get(params["collection_ref"]) is None:
            collection = bpy.data.collections.new(params["collection_ref"])
            scene.collection.children.link(collection)
    elif name == "scene.link_to_collection":
        obj = _object(params["object_ref"])
        collection = bpy.data.collections.get(params["collection_ref"])
        if collection is None:
            raise Refused("unknown_ref", "No collection with that name.")
        if collection.objects.get(obj.name) is None:
            collection.objects.link(obj)
    elif name == "scene.set_units":
        scene.unit_settings.system = params["system"]
        scene.unit_settings.scale_length = params["scale_length"]
    return []

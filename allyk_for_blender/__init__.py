# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 MAYAYAI
"""ALLYK for Blender: run ALLYK's typed design commands in your own Blender.

A thin client of ALLYK's documented Design Bridge API. It pairs once with a
code you type at allyk.app/device, sends minimized scene summaries, and applies
only the allowlisted commands your ALLYK access mode allows. It contains no
ALLYK server logic, prompts, rules or keys, and never listens on a port.
"""
from __future__ import annotations

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy_extras.io_utils import ImportHelper

from . import api, keystore, runner


class ALLYK_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    base_url: StringProperty(name="ALLYK API", default=api.DEFAULT_BASE_URL,
                             description="Design Bridge API address; keep the default unless ALLYK support tells you otherwise")
    output_folder: StringProperty(name="Output folder", subtype="DIR_PATH",
                                  description="Renders and exports from ALLYK commands are written only here")

    def draw(self, context):
        self.layout.prop(self, "output_folder")
        self.layout.prop(self, "base_url")


class ALLYK_OT_pair(bpy.types.Operator):
    bl_idname = "allyk.pair"
    bl_label = "Pair with ALLYK"
    bl_description = "Get a code to type at allyk.app/device while signed in to ALLYK"

    def execute(self, context):
        runner.ensure_worker()
        runner.start_pairing()
        return {"FINISHED"}


class ALLYK_OT_unpair(bpy.types.Operator):
    bl_idname = "allyk.unpair"
    bl_label = "Unpair"
    bl_description = "Delete this device's key; you can also revoke it under Devices in ALLYK"

    def execute(self, context):
        runner.unpair()
        return {"FINISHED"}


class ALLYK_OT_send_snapshot(bpy.types.Operator):
    bl_idname = "allyk.send_snapshot"
    bl_label = "Send scene summary"
    bl_description = "Send object names, types and counts (no geometry, materials or files) to ALLYK"

    character: BoolProperty(default=False, options={"HIDDEN"})

    def execute(self, context):
        target = context.active_object if self.character else None
        if self.character and (target is None or target.type != "MESH"):
            self.report({"WARNING"}, "Select one mesh character first.")
            return {"CANCELLED"}
        runner.ensure_worker()
        runner.send_snapshot(target)
        return {"FINISHED"}


class ALLYK_OT_offer_file(bpy.types.Operator, ImportHelper):
    bl_idname = "allyk.offer_file"
    bl_label = "Make a file available to ALLYK"
    bl_description = "ALLYK can then ask to import this glTF or GLB file; only its name is sent"

    filter_glob: StringProperty(default="*.glb;*.gltf", options={"HIDDEN"})

    def execute(self, context):
        if not self.filepath.lower().endswith((".glb", ".gltf")):
            self.report({"WARNING"}, "Choose a .glb or .gltf file.")
            return {"CANCELLED"}
        keystore.offer_asset(self.filepath)
        runner.send_snapshot()
        return {"FINISHED"}


class ALLYK_OT_toggle(bpy.types.Operator):
    bl_idname = "allyk.toggle_connection"
    bl_label = "Connect"
    bl_description = "While connected, ALLYK for Blender checks for commands every few seconds"

    def execute(self, context):
        runner.ensure_worker()
        runner.state["connected"] = not runner.state["connected"]
        return {"FINISHED"}


class ALLYK_PT_panel(bpy.types.Panel):
    bl_label = "ALLYK"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "ALLYK"

    def draw(self, context):
        layout, state = self.layout, runner.state
        if state["status"] == "waiting_for_user":
            box = layout.box()
            box.label(text="Type this code, signed in to ALLYK:")
            box.label(text=state["user_code"], icon="KEYINGSET")
            box.label(text=state["verification_uri"])
        elif state["status"] != "paired":
            layout.operator("allyk.pair", icon="LINKED")
        else:
            row = layout.row()
            row.operator("allyk.toggle_connection", text="Disconnect" if state["connected"] else "Connect",
                         icon="PAUSE" if state["connected"] else "PLAY", depress=state["connected"])
            layout.operator("allyk.send_snapshot", icon="OUTLINER_OB_GROUP_INSTANCE")
            op = layout.operator("allyk.send_snapshot", text="Send character for check", icon="ARMATURE_DATA")
            op.character = True
            layout.operator("allyk.offer_file", icon="IMPORT")
            layout.operator("allyk.unpair", icon="UNLINKED")
        if state["message"]:
            layout.label(text=state["message"])


_CLASSES = (ALLYK_Preferences, ALLYK_OT_pair, ALLYK_OT_unpair, ALLYK_OT_send_snapshot, ALLYK_OT_offer_file,
            ALLYK_OT_toggle, ALLYK_PT_panel)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    if keystore.load_state().get("linked"):
        runner.state["status"] = "paired"
    if not bpy.app.timers.is_registered(runner.tick):
        bpy.app.timers.register(runner.tick, first_interval=1.0, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(runner.tick):
        bpy.app.timers.unregister(runner.tick)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)

# ALLYK for Blender

ALLYK for Blender connects your own Blender to your ALLYK account. ALLYK can
then set up scenes, render, export and check characters in your Blender, using
only a fixed list of allowed commands. Your .blend files, meshes and textures
stay on your computer.

It is a thin client of ALLYK's Design Bridge API. It contains no ALLYK server
code, prompts, rules or keys, and it never listens on a network port: it only
makes outbound HTTPS requests to allyk.app.

## Install

Requires Blender 4.2 or later (tested with Blender 5.2 LTS).

1. Get the add-on zip. No release is published yet; until then, build it
   from this repository with Blender:
   `blender --command extension build --source-dir allyk_for_blender`
2. In Blender: Edit > Preferences > Get Extensions > Install from Disk, and
   choose the zip.
3. In the add-on's preferences, choose an output folder for renders and
   exports.

ALLYK's Design Bridge is in owner-only testing, so pairing works only for
accounts ALLYK has enabled.

## Pair with ALLYK

1. In the 3D View press N and open the ALLYK tab.
2. Choose **Pair with ALLYK**. A code like `BCDF-GHJK` appears.
3. Open https://allyk.app/device, signed in to ALLYK, type the code and allow.
   ALLYK never sends you a link with the code in it; always type it yourself.

The add-on creates its own key on your computer and keeps it in Blender's
user configuration folder, never in a .blend file. During pairing only a hash
of the key is sent. You can remove the pairing in Blender (**Unpair**) or under
Devices in ALLYK at any time.

## What is sent to ALLYK

- **Scene summary:** object names, types and counts, and the names of files
  you choose to make available. No geometry, materials, textures, paths or
  files.
- **Character summary**, only when you choose **Send character for check**: the
  selected character's name, scale, scene units, collection, material, vertex
  group, shape key and bone names, UV layer count, and counts of non-manifold
  edges, loose vertices and n-gons.
- **Results:** for each command, done, refused or failed, the new scene
  fingerprint, and SHA-256 fingerprints and sizes of files it wrote. Never the
  files themselves.

## What it does

While you have **Connect** switched on, the add-on asks ALLYK for commands
every few seconds and applies them one at a time: import a file you offered,
move, rotate or scale an object, set a camera, a light or a material, render a
still or a turntable, export glTF, and the Character Consistency fixes (apply
scale, rename, create or link a collection, set scene units). Which commands
run without a pause is decided by the access mode you choose in ALLYK; any
approval happens in ALLYK, never in Blender. If the scene changed since ALLYK
planned a run, the add-on refuses it and changes nothing.

## Licence

ALLYK for Blender is free software, licensed under the GNU General Public
License version 3 or (at your option) any later version. See [LICENSE](LICENSE).
Copyright 2026 MAYAYAI.

## Trademarks

ALLYK and MAYAYAI are names and marks of MAYAYAI. The GPL licenses this code;
it does not license the ALLYK or MAYAYAI names or logos. A modified version
must not be presented as ALLYK for Blender or as made by MAYAYAI.

## Contributions

This repository is maintained by MAYAYAI. Outside contributions are not
accepted at this time; please open an issue to report a problem.

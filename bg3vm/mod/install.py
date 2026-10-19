"""Install a built mod into the BG3 user folder and register it in modsettings.lsx."""
from __future__ import annotations

import shutil
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from bg3vm.mod.package import BuiltMod

_EMPTY = """<?xml version="1.0" encoding="UTF-8"?>
<save>
  <version major="4" minor="0" revision="9" build="331"/>
  <region id="ModuleSettings">
    <node id="root">
      <children>
        <node id="Mods"><children/></node>
      </children>
    </node>
  </region>
</save>
"""


def _mods_children(tree: ET.ElementTree) -> ET.Element:
    for node in tree.iter("node"):
        if node.get("id") == "Mods":
            ch = node.find("children")
            if ch is None:
                ch = ET.SubElement(node, "children")
            return ch
    raise ValueError("modsettings.lsx has no Mods node")


def register_mod(modsettings: Path, mod: BuiltMod) -> None:
    if modsettings.exists():
        shutil.copy2(modsettings, modsettings.with_name(f"modsettings.lsx.bak-{int(time.time())}"))
        tree = ET.parse(modsettings)
    else:
        modsettings.parent.mkdir(parents=True, exist_ok=True)
        tree = ET.ElementTree(ET.fromstring(_EMPTY))
    children = _mods_children(tree)
    for node in children.findall("node"):
        for a in node.findall("attribute"):
            if a.get("id") == "UUID" and a.get("value") == mod.uuid:
                return  # already registered
    node = ET.SubElement(children, "node", id="ModuleShortDesc")
    for aid, typ, val in [
        ("Folder", "LSString", mod.folder), ("MD5", "LSString", ""), ("Name", "LSString", mod.name),
        ("UUID", "FixedString", mod.uuid), ("Version64", "int64", str(mod.version64)),
    ]:
        ET.SubElement(node, "attribute", id=aid, type=typ, value=val)
    ET.indent(tree)
    tree.write(modsettings, encoding="utf-8", xml_declaration=True)


def install_mod(appdata: Path, mod: BuiltMod) -> Path:
    mods = appdata / "Mods"
    mods.mkdir(parents=True, exist_ok=True)
    dest = mods / mod.pak.name
    shutil.copy2(mod.pak, dest)
    register_mod(appdata / "PlayerProfiles" / "Public" / "modsettings.lsx", mod)
    return dest

"""meta.lsx generation and Version64 packing."""
from __future__ import annotations

import re
import uuid
from xml.sax.saxutils import quoteattr


def pack_version64(major: int, minor: int, revision: int, build: int) -> int:
    return (major << 55) | (minor << 47) | (revision << 31) | build


def safe_folder(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "", name.replace(" ", "_")) or "VoiceMod"


def build_meta_lsx(name: str, folder: str, mod_uuid: str | None = None, author: str = "bg3vm",
                   description: str = "", version=(1, 0, 0, 0)) -> str:
    mod_uuid = mod_uuid or str(uuid.uuid4())
    v64 = pack_version64(*version)
    q = quoteattr
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<save>
  <version major="4" minor="0" revision="9" build="331"/>
  <region id="Config">
    <node id="root">
      <children>
        <node id="Dependencies"/>
        <node id="ModuleInfo">
          <attribute id="Author" type="LSString" value={q(author)}/>
          <attribute id="Name" type="LSString" value={q(name)}/>
          <attribute id="Description" type="LSString" value={q(description)}/>
          <attribute id="Folder" type="LSString" value={q(folder)}/>
          <attribute id="UUID" type="FixedString" value={q(mod_uuid)}/>
          <attribute id="Version64" type="int64" value="{v64}"/>
          <attribute id="MD5" type="LSString" value=""/>
          <attribute id="Type" type="FixedString" value="Add-on"/>
          <attribute id="Tags" type="LSString" value=""/>
        </node>
      </children>
    </node>
  </region>
</save>
"""

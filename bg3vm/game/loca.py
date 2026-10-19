"""Reader for Larian .loca localization files (content handle -> text)."""
from __future__ import annotations

import struct

_ENTRY = struct.Struct("<64sHI")


def parse_loca(data: bytes) -> dict[str, str]:
    if data[:4] != b"LOCA":
        raise ValueError("not a LOCA file")
    count, text_off = struct.unpack_from("<II", data, 4)
    pos, tpos = 12, text_off
    out: dict[str, str] = {}
    for _ in range(count):
        key, _ver, length = _ENTRY.unpack_from(data, pos)
        pos += _ENTRY.size
        text = data[tpos : tpos + max(length - 1, 0)].decode("utf-8", "replace")
        tpos += length
        out[key.split(b"\0", 1)[0].decode()] = text
    return out


def build_loca(entries: dict[str, str]) -> bytes:
    """Writer, used for tests and fixtures."""
    head, texts = bytearray(), bytearray()
    for key, text in entries.items():
        tb = text.encode("utf-8") + b"\0"
        head += _ENTRY.pack(key.encode(), 1, len(tb))
        texts += tb
    return b"LOCA" + struct.pack("<II", len(entries), 12 + len(head)) + bytes(head) + bytes(texts)

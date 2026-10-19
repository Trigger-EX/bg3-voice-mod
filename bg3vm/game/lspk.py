"""LSPK v18 package reader/writer (Larian .pak), pure Python.

Layout (v18): 'LSPK' | u32 version | u64 file-list offset | u32 file-list size | u8 flags |
u8 priority | 16B md5 | u16 num parts. File list: u32 num files | u32 compressed size |
LZ4 block of 272-byte entries (256B name, u32 off_lo, u16 off_hi, u8 part, u8 flags,
u32 size on disk, u32 uncompressed size). [UNVERIFIED against a real BG3 pak.]
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

import lz4.block

MAGIC = b"LSPK"
VERSION = 18
HEADER = struct.Struct("<4sIQIBB16sH")
ENTRY = struct.Struct("<256sIHBBII")
COMP_NONE, COMP_ZLIB, COMP_LZ4, COMP_ZSTD = 0, 1, 2, 3


@dataclass
class PakEntry:
    name: str
    offset: int
    part: int
    method: int
    size_on_disk: int
    size: int


class PakReader:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.entries: dict[str, PakEntry] = {}
        with open(self.path, "rb") as f:
            magic, version, list_off, list_size, _flags, _prio, _md5, parts = HEADER.unpack(
                f.read(HEADER.size)
            )
            if magic != MAGIC:
                raise ValueError(f"{self.path}: not an LSPK package")
            if version != VERSION:
                raise ValueError(f"{self.path}: unsupported LSPK version {version}")
            self.num_parts = parts
            f.seek(list_off)
            num_files, comp_size = struct.unpack("<II", f.read(8))
            raw = lz4.block.decompress(f.read(comp_size), uncompressed_size=num_files * ENTRY.size)
        for i in range(num_files):
            name, lo, hi, part, flags, disk, unc = ENTRY.unpack_from(raw, i * ENTRY.size)
            name = name.split(b"\0", 1)[0].decode("utf-8")
            method = flags & 0x0F
            size = disk if method == COMP_NONE else unc
            self.entries[name] = PakEntry(name, lo | (hi << 32), part, method, disk, size)

    def _part_path(self, part: int) -> Path:
        if part == 0:
            return self.path
        return self.path.with_name(f"{self.path.stem}_{part}{self.path.suffix}")

    def names(self) -> list[str]:
        return list(self.entries)

    def read(self, name: str) -> bytes:
        e = self.entries[name]
        with open(self._part_path(e.part), "rb") as f:
            f.seek(e.offset)
            data = f.read(e.size_on_disk)
        if e.method == COMP_NONE:
            return data
        if e.method == COMP_LZ4:
            return lz4.block.decompress(data, uncompressed_size=e.size)
        if e.method == COMP_ZLIB:
            return zlib.decompress(data)
        if e.method == COMP_ZSTD:
            import zstandard

            return zstandard.ZstdDecompressor().decompress(data, max_output_size=e.size)
        raise ValueError(f"unknown compression method {e.method}")


def write_pak(path: str | Path, files: dict[str, bytes], priority: int = 0) -> None:
    """Write a single-part, uncompressed-data LSPK v18 package."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    table = bytearray()
    offset = HEADER.size
    blobs = []
    for name, data in files.items():
        nb = name.replace("\\", "/").encode("utf-8")
        if len(nb) >= 256:
            raise ValueError(f"path too long for LSPK: {name}")
        table += ENTRY.pack(nb, offset & 0xFFFFFFFF, offset >> 32, 0, COMP_NONE, len(data), 0)
        blobs.append(data)
        offset += len(data)
    packed = lz4.block.compress(bytes(table), store_size=False)
    with open(path, "wb") as f:
        f.write(HEADER.pack(MAGIC, VERSION, offset, len(packed) + 8, 0, priority, b"\0" * 16, 1))
        for b in blobs:
            f.write(b)
        f.write(struct.pack("<II", len(files), len(packed)))
        f.write(packed)

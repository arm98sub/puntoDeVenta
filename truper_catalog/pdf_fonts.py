from __future__ import annotations

import re
import struct
from collections.abc import Mapping


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from(">H", data, offset)[0]


def _s16(data: bytes, offset: int) -> int:
    return struct.unpack_from(">h", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def reverse_ttf_cmap(data: bytes) -> dict[int, str]:
    """Devuelve glyph-id -> Unicode usando formatos cmap 4 y 12."""
    num_tables = _u16(data, 4)
    tables = {}
    for index in range(num_tables):
        offset = 12 + index * 16
        tag = data[offset:offset + 4].decode("latin-1")
        tables[tag] = (_u32(data, offset + 8), _u32(data, offset + 12))
    if "cmap" not in tables:
        return {}
    cmap_offset, _ = tables["cmap"]
    count = _u16(data, cmap_offset + 2)
    subtables = []
    for index in range(count):
        record = cmap_offset + 4 + index * 8
        platform, encoding = _u16(data, record), _u16(data, record + 2)
        sub = cmap_offset + _u32(data, record + 4)
        fmt = _u16(data, sub)
        priority = (fmt == 12, platform in {0, 3}, encoding in {1, 10})
        if fmt in {4, 12}:
            subtables.append((priority, fmt, sub))
    reverse: dict[int, str] = {}
    for _, fmt, sub in sorted(subtables):
        pairs = _parse_format_4(data, sub) if fmt == 4 else _parse_format_12(data, sub)
        for codepoint, glyph_id in pairs:
            if not (32 <= codepoint <= 0x10FFFF):
                continue
            char = chr(codepoint)
            current = reverse.get(glyph_id)
            if current is None or (char.isascii() and not current.isascii()):
                reverse[glyph_id] = char
    return reverse


def glyph_bytes(data: bytes) -> dict[int, bytes]:
    num_tables = _u16(data, 4)
    tables = {}
    for index in range(num_tables):
        offset = 12 + index * 16
        tag = data[offset:offset + 4].decode("latin-1")
        tables[tag] = (_u32(data, offset + 8), _u32(data, offset + 12))
    required = {"head", "maxp", "loca", "glyf"}
    if not required.issubset(tables):
        return {}
    head, _ = tables["head"]
    maxp, _ = tables["maxp"]
    loca, _ = tables["loca"]
    glyf, _ = tables["glyf"]
    long_loca = _s16(data, head + 50) == 1
    count = _u16(data, maxp + 4)
    offsets = []
    for index in range(count + 1):
        value = _u32(data, loca + index * 4) if long_loca else _u16(data, loca + index * 2) * 2
        offsets.append(value)
    return {
        index: data[glyf + offsets[index]:glyf + offsets[index + 1]].rstrip(b"\0")
        for index in range(count) if offsets[index] != offsets[index + 1]
    }


def _parse_format_12(data: bytes, offset: int):
    groups = _u32(data, offset + 12)
    for index in range(groups):
        group = offset + 16 + index * 12
        start, end, glyph = _u32(data, group), _u32(data, group + 4), _u32(data, group + 8)
        for codepoint in range(start, end + 1):
            yield codepoint, glyph + codepoint - start


def _parse_format_4(data: bytes, offset: int):
    seg_count = _u16(data, offset + 6) // 2
    end_base = offset + 14
    start_base = end_base + seg_count * 2 + 2
    delta_base = start_base + seg_count * 2
    range_base = delta_base + seg_count * 2
    for index in range(seg_count):
        end = _u16(data, end_base + index * 2)
        start = _u16(data, start_base + index * 2)
        delta = _s16(data, delta_base + index * 2)
        range_offset = _u16(data, range_base + index * 2)
        for codepoint in range(start, end + 1):
            if codepoint == 0xFFFF:
                continue
            if range_offset == 0:
                glyph = (codepoint + delta) & 0xFFFF
            else:
                address = range_base + index * 2 + range_offset + (codepoint - start) * 2
                if address + 2 > len(data):
                    continue
                glyph = _u16(data, address)
                if glyph:
                    glyph = (glyph + delta) & 0xFFFF
            if glyph:
                yield codepoint, glyph


def font_family_key(name: str) -> str:
    return re.sub(r"^[A-Z]{6}\+", "", name.lstrip("/"))


def build_page_font_maps(pypdf_page) -> dict[str, dict[int, str]]:
    maps: dict[str, dict[int, str]] = {}
    cid_fonts: dict[str, bytes] = {}
    reference_fonts: dict[str, bytes] = {}
    fonts = pypdf_page["/Resources"].get("/Font", {})
    for reference in fonts.values():
        font = reference.get_object()
        name = font_family_key(str(font.get("/BaseFont", "")))
        descendants = font.get("/DescendantFonts")
        if not descendants:
            descriptor = font.get("/FontDescriptor")
            font_file = descriptor.get_object().get("/FontFile2") if descriptor else None
            if font_file:
                reference_fonts[name] = font_file.get_object().get_data()
            continue
        descendant = descendants[0].get_object()
        if str(descendant.get("/CIDToGIDMap")) != "/Identity":
            continue
        descriptor = descendant.get("/FontDescriptor")
        if not descriptor:
            continue
        font_file = descriptor.get_object().get("/FontFile2")
        if not font_file:
            continue
        try:
            cid_data = font_file.get_object().get_data()
            direct = reverse_ttf_cmap(cid_data)
            if direct:
                maps[name] = direct
            cid_fonts[name] = cid_data
        except (IndexError, KeyError, struct.error, UnicodeError):
            continue
    for name, cid_data in cid_fonts.items():
        if maps.get(name) or name not in reference_fonts:
            continue
        reference_data = reference_fonts[name]
        reference_cmap = reverse_ttf_cmap(reference_data)
        reference_glyphs = glyph_bytes(reference_data)
        signature_to_char = {
            glyph: reference_cmap[glyph_id]
            for glyph_id, glyph in reference_glyphs.items()
            if glyph_id in reference_cmap
        }
        maps[name] = {
            glyph_id: signature_to_char[glyph]
            for glyph_id, glyph in glyph_bytes(cid_data).items()
            if glyph in signature_to_char
        }
    return maps


def decode_cids_with_font(text: str, fontname: str, font_maps: Mapping[str, Mapping[int, str]]) -> str:
    mapping = font_maps.get(font_family_key(fontname), {})

    def replace(match: re.Match[str]) -> str:
        cid = int(match.group(1))
        return mapping.get(cid, match.group(0))

    return re.sub(r"\(cid:(\d+)\)", replace, text)

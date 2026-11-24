"""Small, bounded container checks before OpenCV decoding."""

from pathlib import Path

VIDEO_SUFFIXES = (".mp4", ".mov", ".mkv", ".webm", ".avi")
HEADER_BYTES = 64 * 1024
MP4_BRANDS = {
    b"isom", b"iso2", b"iso3", b"iso4", b"iso5", b"iso6", b"iso7", b"iso8",
    b"mp41", b"mp42", b"avc1", b"dash", b"M4V ", b"MSNV",
}


def ebml_number(header, offset, keep_marker=False):
    if offset >= len(header) or header[offset] == 0:
        raise ValueError("Invalid EBML number")
    first = header[offset]
    width = 9 - first.bit_length()
    end = offset + width
    if end > len(header):
        raise ValueError("Incomplete EBML number")
    value = int.from_bytes(header[offset:end], "big")
    if not keep_marker:
        value &= (1 << (7 * width)) - 1
    return value, end


def ebml_container(header):
    try:
        size, pos = ebml_number(header, 4)
        end = pos + size
        if end > len(header):
            return None
        while pos < end:
            element, pos = ebml_number(header, pos, keep_marker=True)
            length, pos = ebml_number(header, pos)
            if pos + length > end:
                return None
            if element == 0x4282 and length <= 8:  # EBML DocType
                return {b"webm": ".webm", b"matroska": ".mkv"}.get(header[pos:pos + length])
            pos += length
    except ValueError:
        return None
    return None


def iso_container(header):
    pos = 0
    # Recognize the real file type before handing the file to FFmpeg.
    while pos + 8 <= len(header):
        size = int.from_bytes(header[pos:pos + 4], "big")
        kind = header[pos + 4:pos + 8]
        if size < 8 or pos + size > len(header):
            return None
        if kind == b"ftyp" and size >= 16:
            brand = header[pos + 8:pos + 12]
            if brand == b"qt  ":
                return ".mov"
            if brand in MP4_BRANDS:
                return ".mp4"
            return None
        if kind not in (b"free", b"wide", b"skip"):
            return None
        pos += size
    return None


def detect_container(path: Path):
    with path.open("rb") as file:
        header = file.read(HEADER_BYTES)
    if header[:4] == b"RIFF" and header[8:12] == b"AVI ":
        return ".avi"
    if header.startswith(b"\x1a\x45\xdf\xa3"):
        return ebml_container(header)
    return iso_container(header)

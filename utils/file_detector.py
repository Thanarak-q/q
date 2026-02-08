"""File type detection utilities.

Uses magic bytes and extensions to determine file types, which is
critical for choosing the right CTF analysis tools.
"""

from __future__ import annotations

import mimetypes
import struct
from pathlib import Path
from typing import Optional

# Magic byte signatures: (offset, bytes, label)
SIGNATURES: list[tuple[int, bytes, str]] = [
    (0, b"\x7fELF", "ELF executable"),
    (0, b"MZ", "PE executable"),
    (0, b"\xca\xfe\xba\xbe", "Mach-O fat binary"),
    (0, b"\xfe\xed\xfa", "Mach-O binary"),
    (0, b"\xcf\xfa\xed\xfe", "Mach-O 64-bit binary"),
    (0, b"PK\x03\x04", "ZIP archive"),
    (0, b"\x1f\x8b", "GZIP archive"),
    (0, b"BZh", "BZIP2 archive"),
    (0, b"\xfd7zXZ\x00", "XZ archive"),
    (0, b"7z\xbc\xaf\x27\x1c", "7z archive"),
    (0, b"\x89PNG\r\n\x1a\n", "PNG image"),
    (0, b"\xff\xd8\xff", "JPEG image"),
    (0, b"GIF87a", "GIF image"),
    (0, b"GIF89a", "GIF image"),
    (0, b"BM", "BMP image"),
    (0, b"%PDF", "PDF document"),
    (0, b"\x00asm", "WebAssembly binary"),
    (0, b"SQLite format 3", "SQLite database"),
    (0, b"RIFF", "RIFF container (WAV/AVI)"),
    (0, b"\x50\x4b\x05\x06", "ZIP (empty archive)"),
    (0, b"Salted__", "OpenSSL encrypted"),
]


def detect_file_type(path: Path) -> str:
    """Detect the type of a file using magic bytes and extension.

    Args:
        path: Path to the file to inspect.

    Returns:
        Human-readable file type description.
    """
    if not path.exists():
        return "file not found"
    if not path.is_file():
        return "not a regular file"

    # Read first 64 bytes for magic detection
    try:
        header = path.read_bytes()[:64]
    except OSError:
        return "unreadable"

    # Check magic signatures
    for offset, magic, label in SIGNATURES:
        end = offset + len(magic)
        if len(header) >= end and header[offset:end] == magic:
            return label

    # Fall back to mimetype by extension
    mime, _ = mimetypes.guess_type(str(path))
    if mime:
        return mime

    # Try to determine if it's text
    try:
        sample = path.read_bytes()[:8192]
        sample.decode("utf-8")
        return "text/plain (UTF-8)"
    except (UnicodeDecodeError, OSError):
        pass

    return "unknown binary"


def is_archive(path: Path) -> bool:
    """Check if a file is a recognised archive format.

    Args:
        path: Path to check.

    Returns:
        True if the file is a ZIP, GZIP, BZIP2, XZ, or 7z archive.
    """
    ft = detect_file_type(path)
    return any(keyword in ft.lower() for keyword in ("zip", "gzip", "bzip2", "xz", "7z"))


def is_executable(path: Path) -> bool:
    """Check if a file is a recognised executable format.

    Args:
        path: Path to check.

    Returns:
        True if the file is ELF, PE, or Mach-O.
    """
    ft = detect_file_type(path)
    return any(keyword in ft.lower() for keyword in ("elf", "pe ", "mach-o"))

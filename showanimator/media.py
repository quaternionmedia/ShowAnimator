"""Image files a painting scene can draw, kept in one folder (``media_dir``)."""

from __future__ import annotations

import re
from pathlib import Path

# A plain file name: any characters except path separators and NUL, no leading dot,
# and an image extension. Spaces, brackets, commas and accents are fine.
IMAGE_NAME = re.compile(r"[^./\\\x00][^/\\\x00]{0,200}\.(?:png|jpe?g|webp|gif)", re.IGNORECASE)


def list_media(folder: Path) -> list[str]:
    if not folder.is_dir():
        return []
    return sorted(p.name for p in folder.iterdir() if p.is_file() and IMAGE_NAME.fullmatch(p.name))


def media_file(folder: Path, name: str) -> Path | None:
    if not IMAGE_NAME.fullmatch(name):
        return None
    path = folder / name
    return path if path.is_file() else None

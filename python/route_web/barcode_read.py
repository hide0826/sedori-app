# -*- coding: utf-8 -*-
"""アップロードされた写真から JAN を読む。仕入DBは更新しない。"""

from __future__ import annotations

import tempfile
from pathlib import Path

from route_web.desktop_bridge import ensure_desktop_importable


def decode_jan_bytes(raw: bytes) -> str:
    if not raw:
        return ""
    ensure_desktop_importable()
    from services.image_service import ImageService

    service = ImageService()
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
        handle.write(raw)
        temp_path = handle.name
    try:
        jan = service.read_barcode_from_image(temp_path, known_jans=None)
        return str(jan or "")
    finally:
        Path(temp_path).unlink(missing_ok=True)

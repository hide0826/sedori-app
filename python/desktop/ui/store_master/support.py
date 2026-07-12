#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""店舗マスタ共通サポート（Google Maps import フォールバック）。"""
from __future__ import annotations

import os
import sys

_desktop_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if _desktop_root in sys.path:
    sys.path.remove(_desktop_root)
sys.path.insert(0, _desktop_root)

try:
    from services.google_maps_service import (
        get_store_info_from_google,
        recover_store_info_with_japanese,
        normalize_stored_japanese_address,
    )
except Exception:
    try:
        service_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../..", "services"))
        if service_path not in sys.path:
            sys.path.insert(0, service_path)
        from google_maps_service import (
            get_store_info_from_google,
            recover_store_info_with_japanese,
            normalize_stored_japanese_address,
        )
    except Exception:
        get_store_info_from_google = None
        recover_store_info_with_japanese = None
        normalize_stored_japanese_address = None

__all__ = [
    "get_store_info_from_google",
    "recover_store_info_with_japanese",
    "normalize_stored_japanese_address",
]

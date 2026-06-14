#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
デスクトップ向け re-export。

desktop/services と python/services の名前衝突を避けるため、
実装ファイルを直接読み込む。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_impl_path = Path(__file__).resolve().parents[2] / "services" / "route_matching_service.py"
_spec = importlib.util.spec_from_file_location("_hirio_route_matching_impl", _impl_path)
if _spec is None or _spec.loader is None:
    raise ImportError(f"route_matching_service の実装が見つかりません: {_impl_path}")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
RouteMatchingService = _mod.RouteMatchingService

__all__ = ["RouteMatchingService"]

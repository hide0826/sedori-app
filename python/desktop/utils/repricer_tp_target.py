#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Re-export shim — canonical: python/utils/repricer_tp_target.py

デスクトップ実行時の utils 名前空間シャドウを避け、API 正の実装を参照する。
"""

from __future__ import annotations

try:
    from desktop.utils._repricer_canonical_loader import reexport_canonical
except ImportError:
    from ._repricer_canonical_loader import reexport_canonical

reexport_canonical("repricer_tp_target", globals())

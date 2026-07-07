#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
python/utils の repricer 共有モジュールを読み込むヘルパー。

デスクトップ実行時は sys.path の都合で `utils.*` が desktop/utils を指すため、
同名シャドウを避けて canonical（python/utils）を file path から読み込む。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_PYTHON_ROOT = Path(__file__).resolve().parents[2]
_LOADED: dict[str, ModuleType] = {}


def load_canonical_repricer_module(module_basename: str) -> ModuleType:
    if module_basename in _LOADED:
        return _LOADED[module_basename]

    path = _PYTHON_ROOT / "utils" / f"{module_basename}.py"
    qualname = f"_hirio_canonical_{module_basename}"
    spec = importlib.util.spec_from_file_location(qualname, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"canonical repricer module not found: {path}")

    mod = importlib.util.module_from_spec(spec)
    sys.modules[qualname] = mod
    spec.loader.exec_module(mod)
    _LOADED[module_basename] = mod
    return mod


def reexport_canonical(module_basename: str, namespace: dict) -> None:
    mod = load_canonical_repricer_module(module_basename)
    names = getattr(mod, "__all__", None)
    if names is None:
        names = [name for name in dir(mod) if not name.startswith("__")]
    for name in names:
        namespace[name] = getattr(mod, name)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ensure_desktop_sys_path の pytest（Track X Phase 2）。"""

from __future__ import annotations

import sys
from pathlib import Path

from desktop.utils.ensure_desktop_sys_path import (
    ensure_desktop_on_sys_path,
    get_desktop_root,
    get_python_root,
)


def test_get_desktop_root_is_desktop_dir():
    root = Path(get_desktop_root())
    assert root.name == "desktop"
    assert (root / "utils" / "ensure_desktop_sys_path.py").is_file()


def test_ensure_desktop_on_sys_path_idempotent_and_order():
    desktop = ensure_desktop_on_sys_path()
    python_root = get_python_root()
    ensure_desktop_on_sys_path()
    assert sys.path[0] == desktop
    assert sys.path[1] == python_root
    assert sys.path.count(desktop) == 1
    assert sys.path.count(python_root) == 1


def test_ensure_desktop_allows_database_and_desktop_package_import():
    ensure_desktop_on_sys_path()
    from database.store_db import StoreDatabase  # noqa: F401
    from desktop.utils.ui_utils import save_table_header_state  # noqa: F401

    assert StoreDatabase is not None
    assert save_table_header_state is not None

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仕入行編集ダイアログ パッケージ。"""
from __future__ import annotations

try:
    from ui.purchase_row_edit.dialog import PurchaseRowEditDialog
except ImportError:
    from .dialog import PurchaseRowEditDialog

__all__ = ["PurchaseRowEditDialog"]

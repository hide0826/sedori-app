#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ルートサマリー UI パッケージ。"""
try:
    from ui.route_summary.widget import RouteSummaryWidget
except ImportError:
    from .widget import RouteSummaryWidget

__all__ = ["RouteSummaryWidget"]

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""route_summary_widget 純関数まわりの pytest（Track E route_summary Phase 0 安全網）。UI 生成なし。"""

from __future__ import annotations

from pathlib import Path

from _source_symbol_loader import load_class_subset, load_module_functions

_SUPPORT = Path(__file__).resolve().parents[1] / "ui" / "route_summary" / "support.py"
_VISIT_MIXIN = Path(__file__).resolve().parents[1] / "ui" / "route_summary" / "visit_table_mixin.py"

_template_include_from_db_value = load_module_functions(
    _SUPPORT, ["_template_include_from_db_value"]
)["_template_include_from_db_value"]

RouteSummaryVisitTableMixin = load_class_subset(
    _VISIT_MIXIN,
    "RouteSummaryVisitTableMixin",
    [
        "_merge_notes_for_template_export",
        "_resolve_store_master_notes",
        "_visit_store_code_from_dict",
    ],
)


def test_template_include_from_db_value():
    assert _template_include_from_db_value(None) is True
    assert _template_include_from_db_value(True) is True
    assert _template_include_from_db_value(False) is False
    assert _template_include_from_db_value(1) is True
    assert _template_include_from_db_value(0) is False
    assert _template_include_from_db_value("x") is True
    assert _template_include_from_db_value("") is False


def test_merge_notes_for_template_export_dedupes():
    merge = RouteSummaryVisitTableMixin._merge_notes_for_template_export
    assert merge("A, B", "B, C") == "A, B, C"
    assert merge("", "  ", None) == ""
    assert merge("foo", "") == "foo"
    assert merge("A, A", "A") == "A"


def test_resolve_store_master_notes_merges_sql_and_custom_fields():
    resolve = RouteSummaryVisitTableMixin._resolve_store_master_notes
    assert resolve(None) == ""
    assert resolve({}) == ""
    assert resolve({"notes": "SQL備考"}) == "SQL備考"
    assert resolve({"custom_fields": {"notes": "CF備考"}}) == "CF備考"
    assert resolve({"notes": "A, B", "custom_fields": {"notes": "B, C"}}) == "A, B, C"


def test_visit_store_code_from_dict_prefers_store_code():
    code = RouteSummaryVisitTableMixin._visit_store_code_from_dict
    assert code({"store_code": "S001", "supplier_code": "LEGACY"}) == "S001"
    assert code({"store_code": "", "supplier_code": "LEGACY"}) == "LEGACY"
    assert code({"supplier_code": "  LEGACY  "}) == "LEGACY"
    assert code({}) == ""

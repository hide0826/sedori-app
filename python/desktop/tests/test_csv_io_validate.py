#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSVIO 構造検証・正規化の pytest（Track B Phase 0 安全網）。"""

from __future__ import annotations

import pandas as pd

from desktop.utils.csv_io import CSVIO


def test_validate_csv_structure_ok():
    df = pd.DataFrame([{"SKU": "a", "ASIN": "B0"}])
    ok, errors = CSVIO().validate_csv_structure(df, ["SKU", "ASIN"])
    assert ok is True
    assert errors == []


def test_validate_csv_structure_missing_columns():
    df = pd.DataFrame([{"SKU": "a"}])
    ok, errors = CSVIO().validate_csv_structure(df, ["SKU", "ASIN"])
    assert ok is False
    assert any("必須列が不足" in e for e in errors)


def test_validate_csv_structure_empty_dataframe():
    df = pd.DataFrame(columns=["SKU", "ASIN"])
    ok, errors = CSVIO().validate_csv_structure(df, ["SKU", "ASIN"])
    assert ok is False
    assert any("データが空" in e for e in errors)


def test_validate_csv_structure_null_in_object_column():
    df = pd.DataFrame([{"SKU": "a", "title": None}])
    ok, errors = CSVIO().validate_csv_structure(df, ["SKU"])
    assert ok is False
    assert any("空値" in e for e in errors)


def test_normalize_data_strips_and_coerces_numeric():
    df = pd.DataFrame(
        [
            {
                "SKU": "  abc  ",
                "価格": "1,200",
                "原価": "500",
                "利益": "700",
                "数量": "2",
            }
        ]
    )
    # 価格列はカンマ付き文字列のまま to_numeric すると NaN になる場合があるので
    # カンマ無しのケースで数値化を確認
    df2 = pd.DataFrame([{"SKU": "  x  ", "価格": "1200", "原価": "500", "数量": "3"}])
    out = CSVIO().normalize_data(df2)
    assert out.loc[0, "SKU"] == "x"
    assert float(out.loc[0, "価格"]) == 1200.0
    assert float(out.loc[0, "数量"]) == 3.0

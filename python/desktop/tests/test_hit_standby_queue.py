#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shared/hit_standby_queue の enqueue / drain 試験。"""
from __future__ import annotations

import sys
from pathlib import Path

_SHARED = Path(r"C:\HIRIO\shared")
if _SHARED.is_dir() and str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from hit_standby_queue import drain_all, enqueue, peek_count  # noqa: E402


def test_enqueue_drain_roundtrip(tmp_path: Path) -> None:
    shared = tmp_path
    rows = [
        {
            "token": "TokAAAAAAAAAA",
            "rule369": "6",
            "tp0": 9000,
            "inventory_row": {"ASIN": "B0TESTAAAAA", "商品名": "A", "仕入れ価格": 1000},
        },
        {
            "token": "TokBBBBBBBBBB",
            "rule369": "3",
            "tp0": 5000,
            "inventory_row": {"ASIN": "B0TESTBBBBB", "商品名": "B", "仕入れ価格": 2000},
        },
    ]
    assert enqueue(rows, shared=shared) == 2
    assert peek_count(shared=shared) == 2

    drained = drain_all(shared=shared)
    assert len(drained) == 2
    assert drained[0]["token"] == "TokAAAAAAAAAA"
    assert drained[0]["inventory_row"]["ASIN"] == "B0TESTAAAAA"
    assert drained[1]["rule369"] == "3"

    # 二重 drain は空
    assert drain_all(shared=shared) == []
    assert peek_count(shared=shared) == 0


def test_enqueue_skips_bad_rows(tmp_path: Path) -> None:
    shared = tmp_path
    n = enqueue(
        [
            {"token": "", "inventory_row": {"ASIN": "X"}},
            {"token": "OkTokOkTokOk1", "inventory_row": {"ASIN": "B0OK"}},
            {"token": "NoRowTokTok1"},
        ],
        shared=shared,
    )
    assert n == 1
    drained = drain_all(shared=shared)
    assert len(drained) == 1
    assert drained[0]["token"] == "OkTokOkTokOk1"

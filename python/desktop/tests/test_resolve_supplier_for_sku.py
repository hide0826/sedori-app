#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import tempfile
from pathlib import Path

import pytest

from desktop.database.store_db import StoreDatabase


@pytest.fixture
def temp_store_db():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "test_hirio.db")
        db = StoreDatabase(db_path=db_path)
        db.add_store(
            {
                "store_code": "BO-12",
                "supplier_code": "C2-001",
                "store_name": "BOOKOFF SUPER BAZAAR テスト店",
                "route_code": "C2",
                "affiliated_route_name": "千葉ルート",
            }
        )
        db.add_store(
            {
                "store_code": "HO-11",
                "supplier_code": "C2-016",
                "store_name": "ホビーオフ テスト店",
                "route_code": "C2",
                "affiliated_route_name": "千葉ルート",
            }
        )
        yield db
        db.close()


def test_resolve_supplier_for_sku_keeps_new_store_code(temp_store_db: StoreDatabase):
    """照合後の新店舗コード BO-12 を旧 supplier_code C2-001 に置き換えない。"""
    resolved = temp_store_db.resolve_supplier_for_sku("BO-12")
    assert resolved is not None
    assert resolved["supplier_code"] == "BO-12"


def test_resolve_supplier_for_sku_keeps_legacy_supplier_code(temp_store_db: StoreDatabase):
    """仕入先列が旧形式 C2-016 の場合はそのまま使う。"""
    resolved = temp_store_db.resolve_supplier_for_sku("C2-016")
    assert resolved is not None
    assert resolved["supplier_code"] == "C2-016"


def test_resolve_supplier_for_sku_legacy_lookup_returns_legacy_code(temp_store_db: StoreDatabase):
    """旧コード C2-001 で検索した場合も C2-001 を返す（後方互換）。"""
    resolved = temp_store_db.resolve_supplier_for_sku("C2-001")
    assert resolved is not None
    assert resolved["supplier_code"] == "C2-001"

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
import tempfile
from pathlib import Path

import pytest

from database.store_db import StoreDatabase


@pytest.fixture
def temp_store_db():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "test_hirio.db")
        db = StoreDatabase(db_path=db_path)
        yield db
        db.close()


def test_is_invalid_route_code_detects_route_name_copy():
    assert StoreDatabase.is_invalid_route_code("つくばルート", "つくばルート")
    assert not StoreDatabase.is_invalid_route_code("R001", "つくばルート")
    assert not StoreDatabase.is_invalid_route_code("", "つくばルート")


def test_ensure_route_code_assigns_r_series_code(temp_store_db: StoreDatabase):
    code = temp_store_db.ensure_route_code("千葉幕張習志野ルート")
    assert code.startswith("R")
    assert code != "千葉幕張習志野ルート"
    assert temp_store_db.get_route_code_by_name("千葉幕張習志野ルート") == code


def test_repair_invalid_route_codes_fixes_existing_bad_data(temp_store_db: StoreDatabase):
    conn = temp_store_db._get_connection()
    cursor = conn.cursor()
    bad_name = "千葉幕張習志野ルート"
    cursor.execute(
        "INSERT INTO routes (route_name, route_code) VALUES (?, ?)",
        (bad_name, bad_name),
    )
    cursor.execute(
        """
        INSERT INTO stores (
            affiliated_route_name, route_code, store_name, store_code
        ) VALUES (?, ?, ?, ?)
        """,
        (bad_name, bad_name, "テスト店舗", "TST-01"),
    )
    conn.commit()

    repairs = temp_store_db.repair_invalid_route_codes()
    assert len(repairs) == 1
    assert repairs[0]["route_name"] == bad_name
    assert repairs[0]["old_code"] == bad_name
    assert repairs[0]["new_code"].startswith("R")

    store = temp_store_db.list_stores()[0]
    assert store["route_code"] == repairs[0]["new_code"]
    assert temp_store_db.get_route_code_by_name(bad_name) == repairs[0]["new_code"]


def test_generate_next_route_code_skips_existing_codes(temp_store_db: StoreDatabase):
    conn = temp_store_db._get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO routes (route_name, route_code) VALUES (?, ?), (?, ?)",
        ("A", "R005", "B", "H1"),
    )
    conn.commit()

    assert temp_store_db.generate_next_route_code() == "R006"


def test_resolve_route_from_template_uses_formal_code(temp_store_db: StoreDatabase):
    from services.store_master_auto_register import resolve_route_from_template

    route_code, route_name = resolve_route_from_template(
        temp_store_db,
        {"route_name": "新規テストルート"},
    )
    assert route_name == "新規テストルート"
    assert route_code.startswith("R")
    assert route_code != route_name

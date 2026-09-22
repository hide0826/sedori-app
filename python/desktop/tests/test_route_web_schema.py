# -*- coding: utf-8 -*-
"""route_web schema / registry smoke tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PYTHON_DIR = Path(__file__).resolve().parents[2]
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from route_web.registry import make_web_id, register_route, resolve_folder, load_route_json, save_route_json
from route_web.schema import build_route_document


def test_make_web_id_sanitizes():
    wid = make_web_id("20260322", "川崎/A")
    assert wid.startswith("20260322_")
    assert "/" not in wid


def test_build_and_roundtrip(tmp_path: Path):
    folder = tmp_path / "20260322test"
    folder.mkdir()
    stores = [
        {"visit_order": 1, "store_code": "HA-01", "store_name": "ハードオフ", "notes": "x"},
        {"visit_order": 2, "store_code": "BO-02", "store_name": "ブックオフ"},
    ]
    web_id = make_web_id("20260322", "test")
    doc = build_route_document(
        web_id=web_id,
        folder_path=str(folder),
        route_date="2026-03-22",
        route_code="R1",
        route_name="test",
        stores=stores,
    )
    (folder / "route.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    register_route(web_id, str(folder), "test", route_date="2026-03-22")
    assert resolve_folder(web_id) == folder
    from route_web.registry import list_route_summaries
    summaries = list_route_summaries()
    assert any(s["web_id"] == web_id and s["available"] for s in summaries)
    loaded = load_route_json(web_id)
    assert loaded is not None
    assert loaded["route_code"] == "R1"
    assert len(loaded["stores"]) == 2
    loaded["departure_time"] = "09:15"
    save_route_json(web_id, loaded)
    again = load_route_json(web_id)
    assert again["departure_time"] == "09:15"


if __name__ == "__main__":
    # pytest 無しでも動く簡易実行
    import tempfile

    test_make_web_id_sanitizes()
    with tempfile.TemporaryDirectory() as td:
        test_build_and_roundtrip(Path(td))
    print("ok route_web schema/registry")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""店舗種別タグ自動判別の単体テスト。"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

_desktop_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _desktop_root not in sys.path:
    sys.path.insert(0, _desktop_root)

from database.store_db import StoreDatabase
from services.store_brand_tag_service import (
    apply_brand_tag_to_store,
    apply_brand_tags_to_all_stores,
    detect_brand_tag_name,
    ensure_brand_store_tags,
    is_brand_tag_name,
    is_quality_tag_name,
    merge_brand_tag_ids,
)


class TestStoreBrandTagService(unittest.TestCase):
    def test_detect_names(self):
        self.assertEqual(detect_brand_tag_name("ブックオフ川口店"), "BOOKOFF系")
        self.assertEqual(detect_brand_tag_name("BOOKOFF PLUS 大宮"), "BOOKOFF系")
        self.assertEqual(
            detect_brand_tag_name("セカンドストリート草加店"), "セカンドストリート系"
        )
        self.assertEqual(detect_brand_tag_name("セカスト越谷"), "セカンドストリート系")
        self.assertEqual(detect_brand_tag_name("ホビーオフ愛川店"), "ハードオフ系")
        self.assertEqual(detect_brand_tag_name("オフハウス久喜店"), "ハードオフ系")
        self.assertEqual(detect_brand_tag_name("ハードオフ久喜店"), "ハードオフ系")
        self.assertEqual(detect_brand_tag_name("オフモール八千代"), "ハードオフ系")
        self.assertEqual(
            detect_brand_tag_name("トレジャーファクトリー所沢"),
            "トレジャーファクトリー系",
        )
        self.assertEqual(
            detect_brand_tag_name("トレファクスタイル"), "トレジャーファクトリー系"
        )
        self.assertEqual(detect_brand_tag_name("ゲオ川口"), "その他")
        self.assertEqual(detect_brand_tag_name(""), "その他")

    def test_group_helpers(self):
        self.assertTrue(is_brand_tag_name("BOOKOFF系"))
        self.assertTrue(is_brand_tag_name("ハードオフ系"))
        self.assertTrue(is_quality_tag_name("大型店舗"))
        self.assertFalse(is_brand_tag_name("大型店舗"))
        self.assertFalse(is_quality_tag_name("BOOKOFF系"))

    def test_ensure_and_apply(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        db = None
        try:
            db = StoreDatabase(path)
            mapping = ensure_brand_store_tags(db)
            self.assertIn("BOOKOFF系", mapping)
            self.assertIn("ハードオフ系", mapping)
            self.assertIn("その他", mapping)

            sid = db.add_store(
                {
                    "store_name": "ブックオフテスト店",
                    "store_code": "BK-1",
                    "affiliated_route_name": None,
                }
            )
            tag_name = apply_brand_tag_to_store(db, int(sid), "ブックオフテスト店")
            self.assertEqual(tag_name, "BOOKOFF系")
            ids = db.get_store_tag_ids(int(sid))
            self.assertIn(mapping["BOOKOFF系"], ids)

            again = apply_brand_tag_to_store(db, int(sid), "ブックオフテスト店")
            self.assertIsNone(again)

            large = [t for t in db.list_store_tags() if t.get("name") == "大型店舗"]
            if large:
                merged = merge_brand_tag_ids(
                    db, "ブックオフテスト店", [int(large[0]["id"])]
                )
                self.assertIn(int(large[0]["id"]), merged)
                self.assertIn(mapping["BOOKOFF系"], merged)

            sid2 = db.add_store(
                {
                    "store_name": "ハードオフテスト",
                    "store_code": "HA-1",
                }
            )
            stats = apply_brand_tags_to_all_stores(db, replace_existing_brand=True)
            self.assertGreaterEqual(stats["updated"], 1)
            ids2 = db.get_store_tag_ids(int(sid2))
            self.assertIn(mapping["ハードオフ系"], ids2)
        finally:
            if db is not None:
                db.close()
            try:
                os.unlink(path)
            except OSError:
                pass

    def test_rename_legacy_tags(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        db = None
        try:
            db = StoreDatabase(path)
            old_id = db.add_store_tag(
                {
                    "name": "セカスト系",
                    "color": "#111111",
                    "priority": 41,
                    "display_order": 11,
                    "is_active": 1,
                }
            )
            sid = db.add_store({"store_name": "セカストテスト", "store_code": "SS-1"})
            db.set_store_tag_ids(int(sid), [int(old_id)])
            ensure_brand_store_tags(db)
            active_names = {
                t["name"] for t in db.list_store_tags(active_only=True)
            }
            self.assertIn("セカンドストリート系", active_names)
            # 旧タグは無効化され、正式名タグへリンク移行
            old_row = next(t for t in db.list_store_tags(active_only=False) if int(t["id"]) == int(old_id))
            self.assertFalse(bool(old_row.get("is_active", 1)))
            mapping = ensure_brand_store_tags(db)
            self.assertIn(mapping["セカンドストリート系"], db.get_store_tag_ids(int(sid)))
        finally:
            if db is not None:
                db.close()
            try:
                os.unlink(path)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()

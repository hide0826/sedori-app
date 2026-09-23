#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""フリマ仕入証憑サービスの pytest（フォルダ名・フリマ判定・保存）。"""
from __future__ import annotations

from pathlib import Path

from desktop.services.flea_market_evidence_service import (
    EVIDENCE_FOLDER_COL,
    EVIDENCE_GCS_PREFIX,
    EVIDENCE_IMAGE_COLS,
    PURCHASE_CHANNEL_COL,
    build_evidence_folder_name,
    transaction_id_match_key,
    channel_code_for_source,
    gcs_blob_name,
    infer_purchase_channel,
    purchase_channel_from_supplier,
    is_flea_purchase_row,
    is_flea_purchase_source,
    normalize_purchase_channel,
    record_fields_from_save,
    resolve_or_create_evidence_dir,
    save_evidence_bundle,
    save_slot_images,
    _load_gcs_upload_fn,
    _resolve_gcs_uploader_path,
)

_MARKETS = [
    {
        "platform_name": "メルカリ",
        "platform_code": "MRC",
        "code_prefix": "MRC",
    },
    {
        "platform_name": "ラクマ",
        "platform_code": "RAK",
        "code_prefix": "RAK",
    },
]


def test_is_flea_purchase_source_name_and_code():
    assert is_flea_purchase_source("メルカリ", _MARKETS) is True
    assert is_flea_purchase_source("MRC", _MARKETS) is True
    assert is_flea_purchase_source("フリマ:メルカリ", _MARKETS) is True
    assert is_flea_purchase_source("HA01", _MARKETS) is False
    assert is_flea_purchase_source("", _MARKETS) is False
    assert is_flea_purchase_source("mercari", None) is True
    assert is_flea_purchase_source("オンラインメルカリ", None) is True


def test_is_flea_purchase_row_from_url_and_item_id():
    assert is_flea_purchase_row({"仕入先": "メルカリ"}, _MARKETS) is True
    assert is_flea_purchase_row(
        {"出品URL": "https://jp.mercari.com/item/m91911023587"},
        _MARKETS,
    ) is True
    assert is_flea_purchase_row({"取引ID": "m91911023587"}, _MARKETS) is True
    assert is_flea_purchase_row({"仕入先": "HA01", "コメント": "[単品仕入][フリマ:メルカリ]"}, _MARKETS) is True
    assert is_flea_purchase_row({"仕入先": "HA01"}, _MARKETS) is False


def test_purchase_channel_from_supplier_ignores_comment():
    assert purchase_channel_from_supplier({"仕入先": "メルカリ", "コメント": "ヤフオク"}) == "メルカリ"
    assert purchase_channel_from_supplier({"仕入れ先": "楽天", "コメント": "メルカリ"}) == "楽天"
    assert purchase_channel_from_supplier({"コメント": "メルカリ"}) == ""


def test_infer_purchase_channel_from_supplier_and_url():
    assert normalize_purchase_channel("MRC") == "メルカリ"
    assert infer_purchase_channel({"仕入先": "メルカリ"}) == "メルカリ"
    assert infer_purchase_channel({"仕入先": "HA01"}) == "HA01"
    assert infer_purchase_channel(
        {"出品URL": "https://jp.mercari.com/item/m12345678901"}
    ) == "メルカリ"
    assert infer_purchase_channel({"仕入チャネル": "楽天"}) == "楽天"
    assert PURCHASE_CHANNEL_COL == "仕入チャネル"


def test_channel_code_and_folder_name():
    assert channel_code_for_source("メルカリ", _MARKETS) == "MRC"
    name = build_evidence_folder_name("2026/8/18 19:55", "MRC", "B00NMM0VI")
    assert name == "2026-08-18_MRC_B00NMM0VI"
    name2 = build_evidence_folder_name("2026-08-18 19:55", "MRC", "")
    assert name2.endswith("_MRC_NOASIN")


def test_folder_name_strips_invalid_chars():
    name = build_evidence_folder_name("2026-08-18", "M:R*C", "B00XX")
    assert ":" not in name
    assert "*" not in name


def test_resolve_or_create_reuses_existing(tmp_path: Path):
    folder_name = "2026-08-18_MRC_B00NMM0VI"
    first = resolve_or_create_evidence_dir(str(tmp_path), folder_name)
    marker = first / "keep.txt"
    marker.write_text("ok", encoding="utf-8")
    second = resolve_or_create_evidence_dir(str(tmp_path), folder_name)
    assert first == second
    assert marker.is_file()


def test_save_slot_images_and_bundle(tmp_path: Path):
    src1 = tmp_path / "a.png"
    src2 = tmp_path / "b.png"
    src1.write_bytes(b"PNG1")
    src2.write_bytes(b"PNG2")
    dest = tmp_path / "dest"
    saved = save_slot_images(dest, [str(src1), None, str(src2)])
    assert Path(saved[0]).name == "01_listing.png"
    assert saved[1] == ""
    assert Path(saved[2]).name == "03_transaction.png"
    assert Path(saved[0]).read_bytes() == b"PNG1"

    uploaded = []

    def fake_upload(local: str, blob: str) -> str:
        uploaded.append(blob)
        return f"https://storage.googleapis.com/hirio-images-main/{blob}"

    result = save_evidence_bundle(
        root=str(tmp_path / "root"),
        purchase_datetime="2026-08-18 19:55",
        store_value="メルカリ",
        asin="B00NMM0VI",
        slot_sources=[str(src1), None, str(src2)],
        flea_markets=_MARKETS,
        upload_fn=fake_upload,
        upload_to_gcs=True,
    )
    assert result.folder_name == "2026-08-18_MRC_B00NMM0VI"
    assert Path(result.folder_path).is_dir()
    assert len(uploaded) == 2
    assert uploaded[0].startswith(EVIDENCE_GCS_PREFIX)
    assert "used_items/" not in uploaded[0]
    fields = record_fields_from_save(result)
    assert fields[EVIDENCE_FOLDER_COL] == result.folder_path
    assert fields[EVIDENCE_IMAGE_COLS[0]]
    assert fields[EVIDENCE_IMAGE_COLS[1]] == ""
    assert result.gcs_urls[0].startswith("https://")


def test_transaction_id_match_key():
    assert transaction_id_match_key({"取引ID": "m91911023587"}) == "TX:m91911023587"
    assert transaction_id_match_key({"取引ID": ""}) is None
    assert transaction_id_match_key({}) is None


def test_gcs_blob_name_uses_evidence_prefix():
    blob = gcs_blob_name("2026-08-18_MRC_B00NMM0VI", "03_transaction.png")
    assert blob == "purchase_evidence/2026-08-18_MRC_B00NMM0VI/03_transaction.png"


def test_gcs_uploader_is_found_outside_desktop_utils():
    path = _resolve_gcs_uploader_path()
    assert path is not None
    assert path.name == "gcs_uploader.py"
    assert path.is_file()
    assert "desktop" not in path.parts[-3:]
    fn = _load_gcs_upload_fn()
    assert callable(fn)


def test_gcs_failure_keeps_local(tmp_path: Path):
    src = tmp_path / "a.png"
    src.write_bytes(b"PNG1")

    def boom(_local: str, _blob: str) -> str:
        raise RuntimeError("network")

    result = save_evidence_bundle(
        root=str(tmp_path / "root"),
        purchase_datetime="2026-08-18 19:55",
        store_value="MRC",
        asin="B00NMM0VI",
        slot_sources=[str(src), None, None],
        flea_markets=_MARKETS,
        upload_fn=boom,
        upload_to_gcs=True,
    )
    assert result.local_paths[0]
    assert Path(result.local_paths[0]).is_file()
    assert result.gcs_urls[0] == ""
    assert "network" in result.gcs_error

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
画像ファイルの SKU ベース命名ヘルパー。

形式: {出品者SKU}_1.jpg, {出品者SKU}_2.jpg, ...

Amazon形式（SKU.MAIN.jpg / SKU.PT01.jpg）は読み取り互換のみ。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Sequence, Tuple, TypeVar

T = TypeVar("T")

_LEGACY_VARIANT_PATTERN = re.compile(r"^(.+?)_(\d+)$")
_LEGACY_SKU_FILE_PATTERN = re.compile(r"^(.+?)_(\d+)(\.\w+)$", re.IGNORECASE)
_CAMERA_FILENAME_PREFIXES = ("pxl_", "img_", "dsc", "mvimg_", "photo_", "screenshot")
_AMAZON_VARIANT_PATTERN = re.compile(r"^(.+)\.(MAIN|PT\d{2})$", re.IGNORECASE)
_AMAZON_SKU_FILE_PATTERN = re.compile(
    r"^(.+)\.(MAIN|PT\d{2})(\.[^.]+)$",
    re.IGNORECASE,
)


def build_sku_indexed_filename(sku: str, product_index: int, extension: str) -> str:
    """商品写真の並び（0始まり）から {SKU}_1 形式のファイル名を生成する。"""
    sku = str(sku or "").strip()
    if not sku:
        raise ValueError("SKUが空です")
    ext = extension if extension.startswith(".") else f".{extension}"
    return f"{sku}_{product_index + 1}{ext}"


# 後方互換エイリアス
build_amazon_image_filename = build_sku_indexed_filename


def _is_structured_sku_prefix(prefix: str) -> bool:
    """
    仕入SKU形式（例: 20260613-HA-29-1545-3P-027）かどうか。
    PXL_20260620 のようなカメラ仮名は除外する。
    """
    p = str(prefix or "").strip()
    if not p:
        return False
    lower = p.lower()
    if lower.startswith(_CAMERA_FILENAME_PREFIXES):
        return False
    if re.match(r"^\d{8}-", p):
        return True
    if "-" in p:
        return True
    return False


def _parse_legacy_sku_filename(filename: str) -> Optional[Tuple[str, str]]:
    """{SKU}_数字.拡張子 を分解。カメラ仮名は None。"""
    name = Path(filename).name
    match = _LEGACY_SKU_FILE_PATTERN.match(name)
    if not match:
        return None
    prefix = match.group(1)
    if not _is_structured_sku_prefix(prefix):
        return None
    return prefix, match.group(2)


def is_legacy_sku_filename(filename: str, sku: Optional[str] = None) -> bool:
    """旧形式 {SKU}_数字.拡張子 かどうか。"""
    parsed = _parse_legacy_sku_filename(filename)
    if not parsed:
        return False
    if sku is None:
        return True
    return parsed[0] == sku


def is_amazon_sku_filename(filename: str, sku: Optional[str] = None) -> bool:
    """Amazon形式 {SKU}.MAIN|.PTxx.拡張子 かどうか（読み取り互換）。"""
    name = Path(filename).name
    match = _AMAZON_SKU_FILE_PATTERN.match(name)
    if not match:
        return False
    if sku is None:
        return True
    variant = match.group(2).upper()
    valid = {"MAIN"} | {f"PT{i:02d}" for i in range(1, 9)}
    return match.group(1) == sku and variant in valid


def extract_sku_from_image_stem(stem: str) -> Optional[str]:
    """拡張子を除いたファイル名からSKUを抽出（_1 / .MAIN の両対応）。"""
    if not stem:
        return None
    legacy_match = _LEGACY_VARIANT_PATTERN.match(stem)
    if legacy_match:
        prefix = legacy_match.group(1)
        if _is_structured_sku_prefix(prefix):
            return prefix
    amazon_match = _AMAZON_VARIANT_PATTERN.match(stem)
    if amazon_match:
        variant = amazon_match.group(2).upper()
        valid = {"MAIN"} | {f"PT{i:02d}" for i in range(1, 9)}
        if variant in valid:
            return amazon_match.group(1)
    return None


def extract_sku_from_image_path(image_path: str) -> Optional[str]:
    """画像パスからSKUを抽出する。"""
    try:
        return extract_sku_from_image_stem(Path(image_path).stem)
    except Exception:
        return None


def product_image_slots_from_sorted_images(
    sorted_images: Sequence[T],
    *,
    exclude_first: bool,
) -> List[T]:
    """
    撮影日時順の画像リストから、商品写真スロットを返す。
    exclude_first=True のとき先頭1枚（バーコード想定）を除外する。
    """
    if not sorted_images:
        return []
    if exclude_first:
        return list(sorted_images[1:])
    return list(sorted_images)


def plan_amazon_rename_targets(
    sorted_images: Sequence[T],
    sku: str,
    *,
    exclude_first: bool,
    path_getter=lambda r: r.path,  # type: ignore[attr-defined]
) -> List[Tuple[T, str]]:
    """
    {SKU}_1 形式へのリネーム計画を作成する。
    既に {SKU}_数字 形式のファイルはスキップする。
    """
    sku = str(sku or "").strip()
    if not sku:
        return []

    slots = product_image_slots_from_sorted_images(sorted_images, exclude_first=exclude_first)
    operations: List[Tuple[T, str]] = []

    for product_idx, record in enumerate(slots):
        source_path = Path(str(path_getter(record)))
        if is_hirio_rerename_temp_filename(source_path.name):
            continue
        extension = source_path.suffix or ".jpg"
        target_name = build_sku_indexed_filename(sku, product_idx, extension)
        target_path = source_path.parent / target_name

        current_name = source_path.name
        if current_name == target_name:
            continue
        if is_legacy_sku_filename(current_name, sku):
            continue

        if str(source_path) != str(target_path):
            operations.append((record, str(target_path)))

    return operations


def needs_amazon_sequence_rerename(
    sorted_images: Sequence[T],
    sku: str,
    *,
    exclude_first: bool,
    path_getter=lambda r: r.path,  # type: ignore[attr-defined]
) -> bool:
    """
    商品写真の先頭が _1 でないのに、既に SKU 付きファイル名がある場合 True。
    （_1 削除後に _2 から始まっているケースなど）
    """
    sku = str(sku or "").strip()
    if not sku:
        return False

    slots = product_image_slots_from_sorted_images(sorted_images, exclude_first=exclude_first)
    if not slots:
        return False

    has_sku_named = any(
        is_legacy_sku_filename(Path(str(path_getter(record))).name, sku)
        or is_amazon_sku_filename(Path(str(path_getter(record))).name, sku)
        for record in slots
    )
    if not has_sku_named:
        return False

    first_path = Path(str(path_getter(slots[0])))
    extension = first_path.suffix or ".jpg"
    expected_first = build_sku_indexed_filename(sku, 0, extension)
    return first_path.name != expected_first


def plan_amazon_rerename_targets(
    sorted_images: Sequence[T],
    sku: str,
    *,
    exclude_first: bool,
    path_getter=lambda r: r.path,  # type: ignore[attr-defined]
) -> List[Tuple[T, str]]:
    """{SKU}_1 から振り直すリネーム計画（既存の _2 / .PT01 等も対象）。"""
    sku = str(sku or "").strip()
    if not sku:
        return []

    slots = product_image_slots_from_sorted_images(sorted_images, exclude_first=exclude_first)
    operations: List[Tuple[T, str]] = []

    for product_idx, record in enumerate(slots):
        source_path = Path(str(path_getter(record)))
        if is_hirio_rerename_temp_filename(source_path.name):
            continue
        extension = source_path.suffix or ".jpg"
        target_name = build_sku_indexed_filename(sku, product_idx, extension)
        target_path = source_path.parent / target_name

        if source_path.name == target_name:
            continue

        if str(source_path) != str(target_path):
            operations.append((record, str(target_path)))

    return operations


def infer_sku_from_sorted_images(
    sorted_images: Sequence[T],
    *,
    path_getter=lambda r: r.path,  # type: ignore[attr-defined]
) -> Optional[str]:
    """画像リストからファイル名で SKU を推定する（カメラ仮名は無視）。"""
    for record in sorted_images:
        sku = extract_sku_from_image_path(str(path_getter(record)))
        if sku:
            return sku
    return None


def is_hirio_rerename_temp_filename(filename: str) -> bool:
    """連番振り直しの一時ファイル名かどうか。"""
    return Path(filename).name.startswith(".hirio_rerename_")

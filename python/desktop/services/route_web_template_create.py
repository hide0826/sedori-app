#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ルート地図 / ルート登録から共通で使う Webテンプレート作成。"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


@dataclass
class WebTemplateCreateResult:
    ok: bool
    folder: str = ""
    web_id: str = ""
    home_url: str = ""
    route_url: str = ""
    alt_urls: List[str] = field(default_factory=list)
    excel_ok: bool = False
    excel_name: str = ""
    excel_msg: str = ""
    insurance_dir: str = ""
    insurance_err: str = ""
    server_ok: bool = False
    server_msg: str = ""
    detail: str = ""
    error: str = ""


def create_web_template(
    *,
    route_code: str,
    route_name: str,
    route_date: date,
    stores: Sequence[Dict[str, Any]],
    base_dir: Optional[str] = None,
) -> WebTemplateCreateResult:
    """route.json / Excel保険 / ルート保険登録までを行う。"""
    result = WebTemplateCreateResult(ok=False)
    route_code = (route_code or "").strip()
    route_name = (route_name or "").strip() or route_code
    if not route_code:
        result.error = "ルートコードがありません。"
        return result
    if not stores:
        result.error = "テンプレートに出力する店舗がありません。"
        return result

    store_codes = [
        (s.get("store_code") or s.get("supplier_code"))
        for s in stores
        if s.get("store_code") or s.get("supplier_code")
    ]
    if not store_codes:
        result.error = "店舗コードのある店舗がありません。"
        return result

    route_date_str = route_date.strftime("%Y%m%d")
    route_date_iso = route_date.strftime("%Y-%m-%d")

    standard_ledger = Path(r"D:\せどり総合\店舗せどり仕入リスト入れ\仕入帳")
    resolved_base = (base_dir or "").strip()
    if not resolved_base:
        if Path("D:/").exists() or Path("D:\\").exists():
            try:
                standard_ledger.mkdir(parents=True, exist_ok=True)
                resolved_base = str(standard_ledger.resolve())
            except OSError as exc:
                result.error = f"仕入帳フォルダを作成できません: {exc}"
                return result
        else:
            result.error = (
                "D: ドライブの仕入帳フォルダが使えません。"
                "保存先を指定するか、ルート登録画面から作成してください。"
            )
            return result

    unsafe_chars = '\\/:*?"<>|'
    safe_route_name = "".join(
        "_" if ch in unsafe_chars else ch for ch in route_name.strip()
    )
    folder_name = f"{route_date_str}{safe_route_name}"
    route_folder = Path(resolved_base) / folder_name
    try:
        route_folder.mkdir(parents=True, exist_ok=True)
        (route_folder / "商品画像").mkdir(exist_ok=True)
        (route_folder / "レシート画像").mkdir(exist_ok=True)
        (route_folder / "仕入CSV").mkdir(exist_ok=True)
    except OSError as exc:
        result.error = f"ルート箱を作成できません: {exc}"
        return result

    try:
        from route_web.csv_inbox import inbox_dir

        inbox_dir()
    except Exception as exc:
        print(f"仕入CSV受信箱の作成をスキップ: {exc}")

    # Excel 保険
    excel_name = f"route_template_{safe_route_name}_{route_date_str}.xlsx"
    excel_path = route_folder / excel_name
    excel_ok = False
    excel_msg = ""
    try:
        from utils.template_generator import TemplateGenerator
    except Exception:
        try:
            from desktop.utils.template_generator import TemplateGenerator  # type: ignore
        except Exception:
            TemplateGenerator = None  # type: ignore
    if TemplateGenerator is None:
        excel_msg = "TemplateGenerator が使えないため Excel 未作成"
    else:
        try:
            excel_ok = bool(
                TemplateGenerator.generate_excel_template(
                    str(excel_path),
                    route_name,
                    store_codes,
                    list(stores),
                    route_date,
                )
            )
            if not excel_ok:
                excel_msg = "Excel テンプレ生成に失敗（コンソール参照）"
        except Exception as exc:
            excel_msg = f"Excel 生成エラー: {exc}"
            print(f"Webテンプレ時の Excel 生成失敗: {exc}")

    python_dir = Path(__file__).resolve().parents[2]
    if str(python_dir) not in sys.path:
        sys.path.insert(0, str(python_dir))

    try:
        from route_web.registry import make_web_id, register_route
        from route_web.schema import build_route_document
        from route_web.server_helper import (
            ensure_route_web_running,
            home_url,
            public_base_urls,
            route_page_url,
        )
    except Exception as exc:
        result.error = f"route_web モジュールを読み込めません: {exc}"
        return result

    web_id = make_web_id(route_date_str, safe_route_name)
    doc = build_route_document(
        web_id=web_id,
        folder_path=str(route_folder),
        route_date=route_date_iso,
        route_code=route_code,
        route_name=route_name,
        stores=list(stores),
    )
    route_json = route_folder / "route.json"
    route_json.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    register_route(
        web_id,
        str(route_folder),
        route_name=route_name,
        route_date=route_date_iso,
    )

    insurance_dir = None
    insurance_err = ""
    try:
        from services.route_folder_import import publish_route_insurance

        insurance_dir, insurance_err = publish_route_insurance(
            route_folder,
            excel_path if excel_ok else None,
        )
    except Exception as exc:
        insurance_err = str(exc)
        print(f"ルート保険へのコピー失敗: {exc}")

    ok, srv_msg = ensure_route_web_running()
    fixed = home_url()
    this_route = route_page_url(web_id)
    alts = [home_url(b) for b in public_base_urls()[1:]]

    if insurance_dir is not None:
        drive_line = (
            f"  - ルート保険: {insurance_dir}\n"
            "    （ドライブが同期するのはこのフォルダだけ）\n"
        )
    else:
        drive_line = f"  - ルート保険: コピーできませんでした（{insurance_err}）\n"

    excel_line = (
        f"  - {excel_name}（保険・Drive）\n"
        if excel_ok
        else f"  - Excel 未作成: {excel_msg}\n"
    )
    detail = (
        f"保存先（ローカル仕入帳）:\n{route_folder}\n\n"
        f"作ったもの:\n"
        f"  - route.json\n"
        f"{excel_line}"
        f"{drive_line}"
        f"  - 商品画像\\ / レシート画像\\ / 仕入CSV\\\n\n"
        f"【普段】スマホは固定URL\n{fixed}\n\n"
        f"一覧に「{route_date_iso} / {route_name}」\n"
        f"（個別URL: {this_route}）\n\n"
        f"時刻Web: {srv_msg}"
    )

    result.ok = True
    result.folder = str(route_folder)
    result.web_id = web_id
    result.home_url = fixed
    result.route_url = this_route
    result.alt_urls = alts
    result.excel_ok = excel_ok
    result.excel_name = excel_name
    result.excel_msg = excel_msg
    result.insurance_dir = str(insurance_dir) if insurance_dir else ""
    result.insurance_err = insurance_err or ""
    result.server_ok = bool(ok)
    result.server_msg = srv_msg
    result.detail = detail
    return result

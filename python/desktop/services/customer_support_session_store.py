#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""カスタマー対応AIのチャット履歴永続化（最大10件）。"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

MAX_SESSIONS = 10
_STORE_VERSION = 1


def _store_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "customer_support_sessions.json"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


_LEGACY_TEST_CASE_ID = re.compile(r"^id\d+$", re.IGNORECASE)
_LEGACY_TEST_USER = re.compile(r"^user\d+$", re.IGNORECASE)
_LEGACY_TEST_MSG = re.compile(r"^msg\d+$", re.IGNORECASE)


def is_legacy_test_session(session: Dict[str, Any]) -> bool:
    """開発時の動作確認用ダミーデータを除外する。"""
    case_id = str(session.get("case_id") or "").strip()
    if _LEGACY_TEST_CASE_ID.match(case_id):
        return True
    name = str(session.get("customer_name") or "").strip()
    if not _LEGACY_TEST_USER.match(name):
        return False
    for item in session.get("history") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("role") or "").strip() != "customer":
            continue
        text = str(item.get("text") or "").strip()
        if _LEGACY_TEST_MSG.match(text):
            return True
    return False


def is_persistable_session(session: Dict[str, Any]) -> bool:
    """会話が1件以上ある案件だけ履歴に残す。"""
    history = session.get("history") or []
    if not isinstance(history, list) or not history:
        return False
    for item in history:
        if not isinstance(item, dict):
            continue
        if str(item.get("text") or "").strip():
            return True
    return False


def _storable_session(session: Dict[str, Any]) -> Dict[str, Any]:
    """JSON保存用（product_context は再起動後に SKU から再取得）。"""
    history = session.get("history") or []
    clean_history: List[Dict[str, str]] = []
    if isinstance(history, list):
        for item in history:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip()
            text = str(item.get("text") or "").strip()
            if role and text:
                clean_history.append({"role": role, "text": text})
    return {
        "case_id": str(session.get("case_id") or "").strip(),
        "updated_at": (session.get("updated_at") or _now_iso()),
        "customer_name": str(session.get("customer_name") or "").strip(),
        "sku": str(session.get("sku") or "").strip(),
        "policy_key": str(session.get("policy_key") or "").strip(),
        "policy_label": str(session.get("policy_label") or "").strip(),
        "extra_instructions": str(session.get("extra_instructions") or "").strip(),
        "intro_text": str(session.get("intro_text") or "").strip(),
        "outro_text": str(session.get("outro_text") or "").strip(),
        "history": clean_history,
        "latest_full_reply": str(session.get("latest_full_reply") or "").strip(),
    }


def trim_session_order(order: List[str], sessions: Dict[str, Dict[str, Any]]) -> List[str]:
    """最大件数を超えた古い案件を order / sessions から除去する。"""
    trimmed: List[str] = []
    for case_id in order:
        cid = str(case_id or "").strip()
        if not cid or cid not in sessions:
            continue
        trimmed.append(cid)
        if len(trimmed) >= MAX_SESSIONS:
            break
    drop = [cid for cid in sessions.keys() if cid not in trimmed]
    for cid in drop:
        sessions.pop(cid, None)
    return trimmed


def load_customer_support_sessions() -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    """
    保存済みチャットを読み込む。

    Returns:
        (case_id -> session, 新しい順の case_id リスト)
    """
    path = _store_path()
    sessions: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    if not path.is_file():
        return sessions, order
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        logger.warning("Failed to load customer support sessions: %s", exc)
        return sessions, order

    raw_list = payload.get("sessions") if isinstance(payload, dict) else None
    if not isinstance(raw_list, list):
        return sessions, order

    kept_before_trim = 0
    for raw in raw_list:
        if not isinstance(raw, dict):
            continue
        stored = _storable_session(raw)
        case_id = stored.get("case_id") or ""
        if not case_id:
            continue
        stored["case_id"] = case_id
        if not is_persistable_session(stored) or is_legacy_test_session(stored):
            continue
        sessions[case_id] = stored
        order.append(case_id)
        kept_before_trim += 1

    order = trim_session_order(order, sessions)
    if kept_before_trim != len(raw_list) or len(order) != kept_before_trim:
        # ダミー・不正データを除去したのでストアを書き直す
        if order:
            save_customer_support_sessions(sessions, order)
        else:
            try:
                path.unlink(missing_ok=True)
            except Exception as exc:
                logger.debug("Failed to remove empty session store: %s", exc)
    return sessions, order


def save_customer_support_sessions(
    sessions: Dict[str, Dict[str, Any]],
    order: List[str],
) -> None:
    """チャット履歴を保存（最大10件）。"""
    path = _store_path()
    order = [
        cid
        for cid in trim_session_order(list(order), sessions)
        if cid in sessions
        and is_persistable_session(sessions[cid])
        and not is_legacy_test_session(sessions[cid])
    ]
    for cid in list(sessions.keys()):
        if cid not in order:
            sessions.pop(cid, None)
    stored_list = [_storable_session(sessions[cid]) for cid in order]
    payload = {"version": _STORE_VERSION, "sessions": stored_list}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning("Failed to save customer support sessions: %s", exc)


def touch_session(
    sessions: Dict[str, Dict[str, Any]],
    order: List[str],
    case_id: str,
) -> List[str]:
    """更新日時を更新し、履歴リストの先頭へ移動する。"""
    cid = str(case_id or "").strip()
    if not cid or cid not in sessions:
        return order
    sessions[cid]["updated_at"] = _now_iso()
    new_order = [x for x in order if x != cid]
    new_order.insert(0, cid)
    return trim_session_order(new_order, sessions)

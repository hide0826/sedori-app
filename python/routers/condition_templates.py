"""コンディション説明テンプレート API（hirio.db 読み書き）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from desktop.database.condition_template_db import ConditionTemplateDatabase
from utils.server_db_paths import get_hirio_db_path_for_api

router = APIRouter(prefix="/api/condition-templates", tags=["condition-templates"])

CONDITION_KEYS = ("new", "like_new", "very_good", "good", "acceptable")
CONDITION_NAMES = {
    "new": "新品",
    "like_new": "中古(ほぼ新品)",
    "very_good": "中古(非常に良い)",
    "good": "中古(良い)",
    "acceptable": "中古(可)",
}
DETAIL_FIXED_KEYS = ("取説欠品", "内箱欠品", "取説・内箱欠品")
CUSTOM_KEYS = ("custom1", "custom2", "custom3")


class ConditionItem(BaseModel):
    key: str
    name: str
    description: str = ""


class DetailKeywords(BaseModel):
    keywords: Dict[str, str] = Field(default_factory=dict)
    custom_labels: Dict[str, str] = Field(default_factory=dict)


class ConditionTemplatePayload(BaseModel):
    conditions: List[ConditionItem]
    details: DetailKeywords


def _get_db() -> ConditionTemplateDatabase:
    return ConditionTemplateDatabase(db_path=get_hirio_db_path_for_api())


def _decode_description(text: Optional[str]) -> str:
    return (text or "").replace("\\n", "\n")


def _encode_description(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\n", "\\n").replace("\r", "\\n")


def _db_to_payload(db: ConditionTemplateDatabase) -> Dict[str, Any]:
    rows = db.get_all_conditions()
    by_key = {row["condition_key"]: row for row in rows}
    conditions = [
        {
            "key": key,
            "name": by_key.get(key, {}).get("condition_name") or CONDITION_NAMES[key],
            "description": _decode_description(by_key.get(key, {}).get("description")),
        }
        for key in CONDITION_KEYS
    ]

    missing = db.load_missing_keywords()
    keywords = dict(missing.get("keywords") or {})
    custom_labels = dict(missing.get("custom_labels") or {})

    return {
        "source": "server_db",
        "db_path": db.db_path,
        "conditions": conditions,
        "details": {
            "keywords": keywords,
            "custom_labels": custom_labels,
        },
    }


def _payload_to_db(db: ConditionTemplateDatabase, payload: ConditionTemplatePayload) -> None:
    known = {item.key: item for item in payload.conditions}
    for key in CONDITION_KEYS:
        item = known.get(key)
        name = item.name if item else CONDITION_NAMES[key]
        description = _encode_description(item.description if item else "")
        db.save_condition_description(key, name, description)

    existing = db.load_missing_keywords()
    keywords = dict(existing.get("keywords") or {})
    custom_labels = dict(existing.get("custom_labels") or {})

    for key in DETAIL_FIXED_KEYS + CUSTOM_KEYS:
        if key in payload.details.keywords:
            keywords[key] = payload.details.keywords[key]

    for key in CUSTOM_KEYS:
        if key in payload.details.custom_labels:
            custom_labels[key] = payload.details.custom_labels[key]

    db.save_missing_keywords(
        {
            "keywords": keywords,
            "custom_labels": custom_labels,
            "detection_keywords": existing.get(
                "detection_keywords", ["欠品", "なし", "無し", "欠"]
            ),
        }
    )


@router.get("/health")
def health_check():
    db_path = get_hirio_db_path_for_api()
    exists = Path(db_path).exists()
    readable = False
    error: Optional[str] = None
    if exists:
        try:
            db = _get_db()
            db.get_all_conditions()
            readable = True
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
    return {
        "status": "ok" if readable else ("missing_db" if not exists else "error"),
        "service": "condition-templates",
        "db_path": db_path,
        "db_exists": exists,
        "db_readable": readable,
        "error": error,
    }


@router.get("")
def get_condition_templates():
    try:
        db = _get_db()
        return _db_to_payload(db)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("")
def save_condition_templates(payload: ConditionTemplatePayload):
    try:
        db = _get_db()
        _payload_to_db(db, payload)
        return {"success": True, **_db_to_payload(db)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/reset-conditions")
def reset_conditions():
    try:
        db = _get_db()
        db.reset_to_default()
        return {"success": True, **_db_to_payload(db)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc

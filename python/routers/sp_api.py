"""SP-API 価格改定 API（PWA 向け）。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/sp-api", tags=["sp-api"])


def _ensure_shared_on_path() -> None:
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        shared = ancestor / "shared"
        if (shared / "sp_api_client.py").exists():
            shared_str = str(shared)
            if shared_str not in sys.path:
                sys.path.insert(0, shared_str)
            return


def _get_credentials_status() -> Dict[str, Any]:
    _ensure_shared_on_path()
    from amazon_credentials import get_sp_api_credentials  # noqa: WPS433

    creds = get_sp_api_credentials()
    return {
        "credentials_configured": creds.is_complete,
        "has_seller_id": creds.has_seller_id,
        "source": creds.source,
    }


def _df_row_to_listing(row: Dict[str, Any]) -> Dict[str, Any]:
    def _num(key: str) -> Optional[float]:
        val = row.get(key)
        if val is None or val == "":
            return None
        try:
            return float(str(val).replace(",", ""))
        except (TypeError, ValueError):
            return None

    return {
        "sku": str(row.get("SKU") or row.get("sku") or ""),
        "asin": str(row.get("ASIN") or row.get("asin") or ""),
        "title": str(row.get("title") or ""),
        "price": _num("price"),
        "cost": _num("cost"),
        "akaji": _num("akaji"),
    }


@router.get("/health")
def health_check():
    try:
        status = _get_credentials_status()
        return {
            "status": "ok" if status["credentials_configured"] else "missing_credentials",
            "service": "sp-api",
            **status,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "service": "sp-api",
            "credentials_configured": False,
            "error": str(exc),
        }


@router.post("/fetch-listings")
def fetch_listings():
    """Amazon SP-API から出品一覧を取得（レポート方式。数分かかる場合あり）。"""
    cred_status = _get_credentials_status()
    if not cred_status["credentials_configured"]:
        raise HTTPException(
            status_code=503,
            detail="SP-API 認証情報が未設定です。.env の SP_API_* を確認してください。",
        )
    try:
        try:
            from services.sp_api_inventory import (
                fetch_listings_dataframe_for_repricer,
                write_pricetar_temp_csv,
            )
        except ImportError:
            from desktop.services.sp_api_inventory import (  # type: ignore
                fetch_listings_dataframe_for_repricer,
                write_pricetar_temp_csv,
            )

        df, csv_path, err = fetch_listings_dataframe_for_repricer()
        if err:
            raise HTTPException(status_code=502, detail=err)
        if df.empty:
            raise HTTPException(status_code=404, detail="有効な出品行がありません。")

        csv_content = ""
        if csv_path and Path(csv_path).exists():
            csv_content = Path(csv_path).read_text(encoding="utf-8-sig")
        else:
            csv_path = write_pricetar_temp_csv(df)
            csv_content = Path(csv_path).read_text(encoding="utf-8-sig")

        records = df.to_dict(orient="records")
        listings = [_df_row_to_listing(r) for r in records]
        return {
            "source": "sp_api",
            "count": len(listings),
            "listings": listings,
            "csv_content": csv_content,
            "csv_filename": Path(csv_path).name if csv_path else "sp_api_listings.csv",
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class FollowRepriceRequest(BaseModel):
    listings: List[Dict[str, Any]] = Field(default_factory=list)
    max_listings: int = Field(400, ge=1, le=2000)
    apply_amazon: bool = False
    chase_yen: int = Field(100, ge=0, le=10000)


class PatchPricesRequest(BaseModel):
    items: List[Dict[str, Any]] = Field(default_factory=list)
    dry_run: bool = True
    max_items: int = Field(50, ge=1, le=500)


@router.post("/follow-reprice")
def follow_reprice(body: FollowRepriceRequest):
    """同コンディション最安追従（計算。apply_amazon=true で Amazon PATCH）。"""
    cred_status = _get_credentials_status()
    if not cred_status["credentials_configured"]:
        raise HTTPException(status_code=503, detail="SP-API 認証情報が未設定です。")
    if not body.listings:
        raise HTTPException(status_code=400, detail="listings が空です。先に出品一覧を取得してください。")

    try:
        try:
            from services.sp_api_follow_reprice import run_follow_repricer
        except ImportError:
            from desktop.services.sp_api_follow_reprice import run_follow_repricer  # type: ignore

        # PWA からの listings を repricer 行形式に変換
        rows: List[Dict[str, Any]] = []
        for item in body.listings[: body.max_listings]:
            rows.append(
                {
                    "SKU": item.get("sku") or item.get("SKU") or "",
                    "ASIN": item.get("asin") or item.get("ASIN") or "",
                    "title": item.get("title") or "",
                    "price": item.get("price"),
                    "cost": item.get("cost"),
                    "akaji": item.get("akaji"),
                    "condition": item.get("condition") or "1",
                }
            )

        result = run_follow_repricer(
            rows,
            apply_amazon=body.apply_amazon,
            chase_yen=body.chase_yen,
            max_listings=body.max_listings,
        )
        items = result.get("items") or []
        formatted = []
        for it in items:
            if not isinstance(it, dict):
                continue
            formatted.append(
                {
                    "sku": str(it.get("sku") or ""),
                    "days": it.get("days"),
                    "currentPrice": it.get("price"),
                    "competitorMin": it.get("competitor_min") or it.get("min_price"),
                    "newPrice": it.get("new_price"),
                    "rule": str(it.get("rule") or it.get("reason") or ""),
                }
            )
        patch = result.get("patch") or {}
        return {
            "source": "sp_api",
            "count": len(formatted),
            "items": formatted,
            "changed_count": sum(
                1
                for it in formatted
                if it.get("newPrice") is not None
                and it.get("currentPrice") is not None
                and it["newPrice"] != it["currentPrice"]
            ),
            "patch": patch,
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/patch-prices")
def patch_prices(body: PatchPricesRequest):
    """価格改定結果を Amazon Listings PATCH（dry_run=true は対象件数のみ返す）。"""
    cred_status = _get_credentials_status()
    if not cred_status["credentials_configured"]:
        raise HTTPException(status_code=503, detail="SP-API 認証情報が未設定です。")
    if not body.items:
        raise HTTPException(status_code=400, detail="items が空です。")

    try:
        try:
            from services.sp_api_reprice import apply_price_patches, collect_price_patch_targets
        except ImportError:
            from desktop.services.sp_api_reprice import (  # type: ignore
                apply_price_patches,
                collect_price_patch_targets,
            )

        targets = collect_price_patch_targets(body.items[: body.max_items])
        if body.dry_run:
            return {
                "source": "sp_api",
                "dry_run": True,
                "target_count": len(targets),
                "targets": targets[:20],
            }

        patch_result = apply_price_patches(targets, max_items=body.max_items)
        return {
            "source": "sp_api",
            "dry_run": False,
            **patch_result,
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc

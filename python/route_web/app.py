# -*- coding: utf-8 -*-
"""ルート時刻入力 FastAPI（:8792）。Phase 1〜1.5 / 2 / 5。巡回と商品撮影は別画面。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional
import threading

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from route_web import ROUTE_WEB_PORT
from route_web.csv_inbox import (
    append_csv_file,
    inbox_dir,
    list_inbox_files,
    list_route_csv_files,
    move_from_inbox,
    save_csv_upload,
)
from route_web.product_images import (
    product_dir,
    save_product_upload,
    append_product_file,
    append_route_product_file,
    confirm_product_group,
    confirm_route_product_group,
    confirmed_product_groups,
    discard_product_group,
    list_no_image_products,
    mark_no_image,
    clear_no_image,
    route_file_code,
)
from route_web.prepare import load_prep_status, prepare_route_folder
from route_web.route_purchases import list_route_purchases, lookup_photo_jan, nearby_route_products
from route_web.scan_requests import enqueue_scan
from route_web.receipts import (
    append_receipt_file,
    find_store,
    receipt_dir,
    save_receipt_upload,
)
from route_web.registry import (
    list_route_summaries,
    load_route_json,
    resolve_folder,
    save_route_json,
)
from route_web.schema import stamp_updated
from route_web.store_notes_sync import (
    enrich_store_notes_from_master,
    sync_changed_store_notes_to_master,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
PAGE_PATH = STATIC_DIR / "route.html"
PHOTOS_PATH = STATIC_DIR / "route_photos.html"
PHOTOS_DONE_PATH = STATIC_DIR / "route_photos_done.html"
INDEX_PATH = STATIC_DIR / "index.html"
ICON_PATH = STATIC_DIR / "icon.png"
MANIFEST_PATH = STATIC_DIR / "manifest.webmanifest"
# C:\HIRIO\repo\sedori-app.github\python\route_web → 4つ上が C:\HIRIO
_HIRIO_ROOT = Path(__file__).resolve().parents[4]
TWS_BATTERY_DIR = _HIRIO_ROOT / "tws-battery-check"

app = FastAPI(title="HIRIO Route Web", version="0.3.0")
_prepare_guard = threading.Lock()
_prepare_running: set[str] = set()


class InboxMoveBody(BaseModel):
    filename: str


class ConfirmBody(BaseModel):
    jan: str = ""
    asin: str = ""


def _page_html(web_id: str) -> str:
    if not PAGE_PATH.is_file():
        raise HTTPException(status_code=500, detail="route.html missing")
    html = PAGE_PATH.read_text(encoding="utf-8")
    return html.replace("__WEB_ID__", web_id)


def _index_html() -> str:
    if not INDEX_PATH.is_file():
        raise HTTPException(status_code=500, detail="index.html missing")
    return INDEX_PATH.read_text(encoding="utf-8")


def _require_doc(web_id: str) -> Dict[str, Any]:
    doc = load_route_json(web_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"route not found: {web_id}")
    return doc


def _require_folder(web_id: str) -> Path:
    folder = resolve_folder(web_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="folder missing")
    return folder


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "service": "route_web", "version": "0.3.0"}


@app.get("/icon.png")
@app.get("/apple-touch-icon.png")
@app.get("/apple-touch-icon-precomposed.png")
@app.get("/favicon.ico")
def route_icon() -> FileResponse:
    if not ICON_PATH.is_file():
        raise HTTPException(status_code=404, detail="icon missing")
    return FileResponse(ICON_PATH, media_type="image/png")


@app.get("/manifest.webmanifest")
def route_manifest() -> FileResponse:
    if not MANIFEST_PATH.is_file():
        raise HTTPException(status_code=404, detail="manifest missing")
    return FileResponse(MANIFEST_PATH, media_type="application/manifest+json")


@app.get("/", response_class=HTMLResponse)
def index_page() -> HTMLResponse:
    """固定URL。スマホはこのページだけブックマークすればよい。"""
    return HTMLResponse(_index_html())


@app.get("/api/routes")
def api_routes() -> JSONResponse:
    # ネット仕入れリスト上の箱を自動登録（スマホ一覧に出す）
    try:
        from route_web.online_sync import sync_online_boxes_into_registry

        sync_online_boxes_into_registry()
    except Exception as exc:
        # 一覧取得自体は落とさない
        print(f"[route_web] online sync skipped: {exc}")
    try:
        return JSONResponse({"routes": list_route_summaries()})
    except Exception as exc:
        return JSONResponse(
            {"routes": [], "error": str(exc)},
            status_code=500,
        )


@app.get("/api/csv-inbox")
def api_csv_inbox() -> JSONResponse:
    try:
        path = str(inbox_dir())
        files = list_inbox_files()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"inbox error: {exc}") from exc
    return JSONResponse({"inbox_path": path, "files": files})


@app.get("/route/{web_id}/photos/done", response_class=HTMLResponse)
def route_photos_done_page(web_id: str) -> HTMLResponse:
    _require_doc(web_id)
    if not PHOTOS_DONE_PATH.is_file():
        raise HTTPException(status_code=500, detail="route_photos_done.html missing")
    html = PHOTOS_DONE_PATH.read_text(encoding="utf-8")
    return HTMLResponse(html.replace("__WEB_ID__", web_id))


@app.get("/route/{web_id}/photos", response_class=HTMLResponse)
def route_photos_page(web_id: str) -> HTMLResponse:
    _require_doc(web_id)
    if not PHOTOS_PATH.is_file():
        raise HTTPException(status_code=500, detail="route_photos.html missing")
    html = PHOTOS_PATH.read_text(encoding="utf-8")
    return HTMLResponse(html.replace("__WEB_ID__", web_id))


@app.get("/route/{web_id}", response_class=HTMLResponse)
def route_page(web_id: str):
    doc = _require_doc(web_id)
    kind = str(doc.get("box_kind") or "").strip().lower()
    code = str(doc.get("route_code") or "").strip().upper()
    if kind == "online" or code == "NET":
        return RedirectResponse(url=f"/route/{web_id}/photos", status_code=302)
    return HTMLResponse(_page_html(web_id))


@app.get("/api/route/{web_id}")
def get_route(web_id: str) -> JSONResponse:
    doc = enrich_store_notes_from_master(_require_doc(web_id))
    return JSONResponse(doc)


@app.put("/api/route/{web_id}")
def put_route(web_id: str, body: Dict[str, Any]) -> JSONResponse:
    existing = _require_doc(web_id)
    body = dict(body)
    body["web_id"] = web_id
    body["folder_path"] = existing.get("folder_path") or body.get("folder_path")
    body["schema_version"] = existing.get("schema_version") or 1
    body = stamp_updated(body)
    try:
        sync_changed_store_notes_to_master(existing, body)
    except Exception as exc:
        print(f"店舗マスタ備考同期エラー: {exc}")
    save_route_json(web_id, body)
    return JSONResponse(body)


@app.get("/api/route/{web_id}/csv")
def get_route_csv(web_id: str) -> JSONResponse:
    folder = _require_folder(web_id)
    return JSONResponse({"files": list_route_csv_files(folder)})


@app.post("/api/route/{web_id}/csv/from-inbox")
def move_csv_from_inbox(web_id: str, body: InboxMoveBody) -> JSONResponse:
    doc = _require_doc(web_id)
    folder = _require_folder(web_id)
    name = Path(body.filename or "").name
    if not name:
        raise HTTPException(status_code=400, detail="filename required")
    try:
        saved = move_from_inbox(folder, name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"move failed: {exc}") from exc
    doc = append_csv_file(doc, saved)
    doc = stamp_updated(doc)
    save_route_json(web_id, doc)
    return JSONResponse(
        {
            "ok": True,
            "filename": saved,
            "csv_files": doc.get("csv_files") or [],
            "route": doc,
            "inbox": list_inbox_files(),
            "route_csv": list_route_csv_files(folder),
        }
    )


@app.post("/api/route/{web_id}/csv")
async def upload_csv(web_id: str, file: UploadFile = File(...)) -> JSONResponse:
    doc = _require_doc(web_id)
    folder = _require_folder(web_id)
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty file")
    try:
        saved = save_csv_upload(folder, raw, original_name=file.filename or "")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"save failed: {exc}") from exc
    doc = append_csv_file(doc, saved)
    doc = stamp_updated(doc)
    save_route_json(web_id, doc)
    return JSONResponse(
        {
            "ok": True,
            "filename": saved,
            "csv_files": doc.get("csv_files") or [],
            "route": doc,
            "route_csv": list_route_csv_files(folder),
        }
    )


@app.post("/api/route/{web_id}/stores/{store_code}/receipts")
async def upload_receipt(
    web_id: str,
    store_code: str,
    file: UploadFile = File(...),
) -> JSONResponse:
    doc = _require_doc(web_id)
    folder = _require_folder(web_id)
    if find_store(doc, store_code) is None:
        raise HTTPException(status_code=404, detail=f"store not found: {store_code}")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty file")
    try:
        filename = save_receipt_upload(
            folder,
            str(doc.get("route_date") or ""),
            store_code,
            raw,
            original_name=file.filename or "",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"save failed: {exc}") from exc

    try:
        doc = append_receipt_file(doc, store_code, filename)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    doc = stamp_updated(doc)
    save_route_json(web_id, doc)
    return JSONResponse(
        {
            "ok": True,
            "filename": filename,
            "store_code": store_code,
            "receipt_files": find_store(doc, store_code).get("receipt_files") or [],
            "route": doc,
        }
    )


@app.get("/api/route/{web_id}/receipts/{filename}")
def get_receipt_file(web_id: str, filename: str):
    folder = _require_folder(web_id)
    name = Path(filename).name
    path = receipt_dir(folder) / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path)


@app.post("/api/route/{web_id}/stores/{store_code}/products")
async def upload_product(
    web_id: str,
    store_code: str,
    file: UploadFile = File(...),
    jan: Optional[str] = Form(None),
) -> JSONResponse:
    doc = _require_doc(web_id)
    folder = _require_folder(web_id)
    if find_store(doc, store_code) is None:
        raise HTTPException(status_code=404, detail=f"store not found: {store_code}")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty file")
    try:
        filename = save_product_upload(
            folder,
            str(doc.get("route_date") or ""),
            store_code,
            raw,
            original_name=file.filename or "",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"save failed: {exc}") from exc

    try:
        doc = append_product_file(doc, store_code, filename, jan=jan or "")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    doc = stamp_updated(doc)
    save_route_json(web_id, doc)
    st = find_store(doc, store_code)
    return JSONResponse(
        {
            "ok": True,
            "filename": filename,
            "store_code": store_code,
            "jan": (jan or "").strip(),
            "product_files": (st or {}).get("product_files") or [],
            "route": doc,
        }
    )


def _seed_saved_jan(folder: Path, filename: str, jan: str) -> bool:
    """保存した写真のJANを画像DBへ書く。失敗しても写真自体は残す。"""
    if not str(jan or "").strip():
        return False
    try:
        from route_web.desktop_bridge import ensure_desktop_importable

        ensure_desktop_importable()
        from services.route_product_seed import seed_product_jan

        return bool(seed_product_jan(product_dir(folder) / filename, jan))
    except Exception:
        return False


@app.post("/api/route/{web_id}/products")
async def upload_route_product(
    web_id: str,
    file: UploadFile = File(...),
    jan: Optional[str] = Form(None),
    asin: Optional[str] = Form(None),
) -> JSONResponse:
    """商品写真をルート単位で保存する。店舗は選ばない。"""
    doc = _require_doc(web_id)
    folder = _require_folder(web_id)
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty file")
    code = route_file_code(doc)
    try:
        filename = save_product_upload(
            folder,
            str(doc.get("route_date") or ""),
            code,
            raw,
            original_name=file.filename or "",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"save failed: {exc}") from exc
    doc = append_route_product_file(doc, filename, jan=jan or "", asin=asin or "")
    doc = stamp_updated(doc)
    save_route_json(web_id, doc)
    seeded = _seed_saved_jan(folder, filename, jan or "")
    return JSONResponse(
        {
            "ok": True,
            "filename": filename,
            "jan": (jan or "").strip(),
            "asin": (asin or "").strip(),
            "image_db": seeded,
            "route_code": str(doc.get("route_code") or ""),
            "route_name": str(doc.get("route_name") or ""),
            "product_files": doc.get("product_files") or [],
        }
    )


@app.get("/api/route/{web_id}/products/done")
def get_done_products(web_id: str) -> JSONResponse:
    doc = _require_doc(web_id)
    groups = confirmed_product_groups(doc)
    by_jan: Dict[str, Dict[str, Any]] = {}
    by_asin: Dict[str, Dict[str, Any]] = {}
    try:
        for row in list_route_purchases(doc):
            jan = str(row.get("jan") or "")
            asin = str(row.get("asin") or "")
            if jan and jan not in by_jan:
                by_jan[jan] = row
            if asin and asin not in by_asin:
                by_asin[asin] = row
    except Exception:
        by_jan = {}
        by_asin = {}
    done = []
    seen = set()

    def _append_done(jan: str, asin: str, files: list, no_image: bool) -> None:
        key = ("jan:" + jan) if jan else (("asin:" + asin) if asin else "")
        if not key or key in seen:
            return
        seen.add(key)
        row = by_jan.get(jan) or by_asin.get(asin) or {}
        done.append(
            {
                "jan": jan,
                "asin": asin or row.get("asin") or "",
                "files": files,
                "no_image": no_image,
                "product_name": row.get("product_name") or "",
                "sku": row.get("sku") or "",
                "route_name": str(doc.get("route_name") or ""),
                "route_date": str(doc.get("route_date") or ""),
            }
        )

    no_image_keys = set()
    for item in list_no_image_products(doc):
        jan = item.get("jan") or ""
        asin = item.get("asin") or ""
        key = ("jan:" + jan) if jan else ("asin:" + asin)
        no_image_keys.add(key)
    for group in groups:
        jan = group.get("jan") or ""
        asin = group.get("asin") or ""
        key = ("jan:" + jan) if jan else (("asin:" + asin) if asin else "")
        _append_done(jan, asin, group["files"], key in no_image_keys)
    for item in list_no_image_products(doc):
        _append_done(item.get("jan") or "", item.get("asin") or "", [], True)
    return JSONResponse({"done": done})


@app.post("/api/route/{web_id}/products/reopen")
def reopen_route_products(web_id: str, body: ConfirmBody) -> JSONResponse:
    doc = _require_doc(web_id)
    folder = _require_folder(web_id)
    discarded = False
    try:
        doc = discard_product_group(doc, folder, body.jan or "", body.asin or "")
        discarded = True
    except ValueError:
        discarded = False
    try:
        doc, cleared = clear_no_image(doc, body.jan or "", body.asin or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not discarded and not cleared:
        raise HTTPException(status_code=400, detail="reshoot target not found")
    doc = stamp_updated(doc)
    save_route_json(web_id, doc)
    return JSONResponse({"ok": True})


@app.post("/api/route/{web_id}/products/no-image")
def mark_route_product_no_image(web_id: str, body: ConfirmBody) -> JSONResponse:
    """写真を撮らず、画像不要として撮影済みへ移す。"""
    doc = _require_doc(web_id)
    try:
        doc = mark_no_image(doc, body.jan or "", body.asin or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    doc = stamp_updated(doc)
    save_route_json(web_id, doc)
    return JSONResponse({"ok": True})


@app.post("/api/route/{web_id}/products/confirm")
def confirm_route_products(web_id: str, body: ConfirmBody) -> JSONResponse:
    doc = _require_doc(web_id)
    try:
        doc = confirm_route_product_group(doc, body.jan or "", body.asin or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    doc = stamp_updated(doc)
    save_route_json(web_id, doc)
    return JSONResponse({"ok": True, "route": doc})


@app.get("/api/route/{web_id}/products/{filename}")
def get_product_file(web_id: str, filename: str):
    folder = _require_folder(web_id)
    name = Path(filename).name
    path = product_dir(folder) / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path)


def _run_prepare(web_id: str, folder: Path) -> None:
    try:
        prepare_route_folder(folder)
    finally:
        with _prepare_guard:
            _prepare_running.discard(web_id)


@app.post("/api/route/{web_id}/prepare")
def start_prepare(web_id: str) -> JSONResponse:
    folder = _require_folder(web_id)
    with _prepare_guard:
        if web_id in _prepare_running:
            return JSONResponse({"status": "running", "prep": load_prep_status(folder)})
        _prepare_running.add(web_id)
    threading.Thread(target=_run_prepare, args=(web_id, folder), daemon=True).start()
    return JSONResponse({"status": "started", "prep": load_prep_status(folder)})


@app.get("/api/route/{web_id}/prepare")
def get_prepare(web_id: str) -> JSONResponse:
    folder = _require_folder(web_id)
    status = load_prep_status(folder)
    with _prepare_guard:
        if web_id in _prepare_running and status.get("status") != "running":
            status = dict(status)
            status["status"] = "running"
    return JSONResponse(status)


@app.get("/api/route/{web_id}/purchases")
def get_route_purchases(web_id: str) -> JSONResponse:
    doc = _require_doc(web_id)
    rows = list_route_purchases(doc)
    kind = str(doc.get("box_kind") or "").strip().lower()
    is_online = kind == "online" or str(doc.get("route_code") or "").strip().upper() == "NET"
    nearby = [] if rows or is_online else nearby_route_products(doc)
    if rows:
        message = ""
    elif is_online:
        message = "先にネット仕入タブで「スマホ商品撮影」を押し、候補を書き出してください"
    elif nearby:
        message = "このルートの仕入はまだDBにありません。日付の近いルートの商品です"
    else:
        message = "先に仕入管理で箱を保存してください"
    return JSONResponse(
        {
            "purchases": rows,
            "nearby_routes": nearby,
            "empty": not rows and not nearby,
            "message": message,
        }
    )


@app.post("/api/route/{web_id}/barcode")
async def read_route_barcode(
    web_id: str,
    file: UploadFile = File(...),
    jan: Optional[str] = Form(None),
) -> JSONResponse:
    doc = _require_doc(web_id)
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty file")
    from route_web.barcode_read import decode_jan_bytes

    decoded = decode_jan_bytes(raw)
    looked = lookup_photo_jan(doc, (jan or "").strip() or decoded)
    return JSONResponse(
        {
            "jan": looked.get("jan") or "",
            "level": looked.get("level") or "none",
            "candidates": looked.get("candidates") or [],
            "nearby_routes": looked.get("nearby_routes") or [],
            "message": looked.get("message") or "",
        }
    )


@app.post("/api/route/{web_id}/stores/{store_code}/products/confirm")
def confirm_products(web_id: str, store_code: str, body: ConfirmBody) -> JSONResponse:
    doc = _require_doc(web_id)
    try:
        doc = confirm_product_group(doc, store_code, body.jan or "")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    doc = stamp_updated(doc)
    save_route_json(web_id, doc)
    return JSONResponse({"ok": True, "route": doc})


@app.post("/api/route/{web_id}/products/scan-request")
def request_product_scan(web_id: str) -> JSONResponse:
    folder = _require_folder(web_id)
    item = enqueue_scan(web_id, folder)
    return JSONResponse({"ok": True, "request": item})


# TWSバッテリー検品 API（SQLite: C:\HIRIO\tws-battery-check\data\inspections.db）
if TWS_BATTERY_DIR.is_dir():
    import sys

    tws_path = str(TWS_BATTERY_DIR)
    if tws_path not in sys.path:
        sys.path.insert(0, tws_path)
    try:
        from tws_api import router as tws_battery_router  # type: ignore

        app.include_router(tws_battery_router)
    except Exception as exc:
        print(f"[route_web] tws-battery API not loaded: {exc}")


# TWSバッテリー検品 PWA（既存 Tailscale https の /tws/ で配信）
if TWS_BATTERY_DIR.is_dir():
    app.mount(
        "/tws",
        StaticFiles(directory=str(TWS_BATTERY_DIR), html=True),
        name="tws_battery_check",
    )


def create_app() -> FastAPI:
    return app


def _bind_route_socket():
    """IPv4 と IPv6 の両方で 8792 を待つ。

    houseserver という名前は IPv6 が先に返ることがある。
    uvicorn にホスト名だけ渡すと、Windows では IPv6 だけになり IPv4 が届かない。
    """
    import socket

    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("::", ROUTE_WEB_PORT))
    except OSError:
        sock.close()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", ROUTE_WEB_PORT))
    sock.set_inheritable(True)
    return sock


def main() -> None:
    from uvicorn import Config, Server

    sock = _bind_route_socket()
    config = Config(
        "route_web.app:app",
        host="::",
        port=ROUTE_WEB_PORT,
        reload=False,
    )
    config.load_app()
    server = Server(config=config)
    server.run(sockets=[sock])


if __name__ == "__main__":
    main()

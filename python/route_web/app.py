# -*- coding: utf-8 -*-
"""ルート時刻入力 FastAPI（:8792）。Phase 1〜1.5 / 2 / 5。巡回と商品撮影は別画面。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional
import threading

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
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
    confirm_product_group,
)
from route_web.prepare import load_prep_status, prepare_route_folder
from route_web.route_purchases import list_route_purchases
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

STATIC_DIR = Path(__file__).resolve().parent / "static"
PAGE_PATH = STATIC_DIR / "route.html"
PHOTOS_PATH = STATIC_DIR / "route_photos.html"
INDEX_PATH = STATIC_DIR / "index.html"

app = FastAPI(title="HIRIO Route Web", version="0.3.0")
_prepare_guard = threading.Lock()
_prepare_running: set[str] = set()


class InboxMoveBody(BaseModel):
    filename: str


class ConfirmBody(BaseModel):
    jan: str = ""


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


@app.get("/", response_class=HTMLResponse)
def index_page() -> HTMLResponse:
    """固定URL。スマホはこのページだけブックマークすればよい。"""
    return HTMLResponse(_index_html())


@app.get("/api/routes")
def api_routes() -> JSONResponse:
    return JSONResponse({"routes": list_route_summaries()})


@app.get("/api/csv-inbox")
def api_csv_inbox() -> JSONResponse:
    try:
        path = str(inbox_dir())
        files = list_inbox_files()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"inbox error: {exc}") from exc
    return JSONResponse({"inbox_path": path, "files": files})


@app.get("/route/{web_id}/photos", response_class=HTMLResponse)
def route_photos_page(web_id: str) -> HTMLResponse:
    _require_doc(web_id)
    if not PHOTOS_PATH.is_file():
        raise HTTPException(status_code=500, detail="route_photos.html missing")
    html = PHOTOS_PATH.read_text(encoding="utf-8")
    return HTMLResponse(html.replace("__WEB_ID__", web_id))


@app.get("/route/{web_id}", response_class=HTMLResponse)
def route_page(web_id: str) -> HTMLResponse:
    _require_doc(web_id)
    return HTMLResponse(_page_html(web_id))


@app.get("/api/route/{web_id}")
def get_route(web_id: str) -> JSONResponse:
    return JSONResponse(_require_doc(web_id))


@app.put("/api/route/{web_id}")
def put_route(web_id: str, body: Dict[str, Any]) -> JSONResponse:
    existing = _require_doc(web_id)
    body = dict(body)
    body["web_id"] = web_id
    body["folder_path"] = existing.get("folder_path") or body.get("folder_path")
    body["schema_version"] = existing.get("schema_version") or 1
    body = stamp_updated(body)
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
    return JSONResponse(
        {
            "purchases": rows,
            "empty": not rows,
            "message": "" if rows else "先に仕入管理で箱を保存してください",
        }
    )


@app.post("/api/route/{web_id}/barcode")
async def read_route_barcode(web_id: str, file: UploadFile = File(...)) -> JSONResponse:
    doc = _require_doc(web_id)
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty file")
    from route_web.barcode_read import decode_jan_bytes

    jan = decode_jan_bytes(raw)
    purchases = list_route_purchases(doc)
    candidates = [row for row in purchases if jan and row.get("jan") == jan]
    return JSONResponse(
        {
            "jan": jan or "",
            "candidates": candidates,
            "purchases_empty": not purchases,
            "message": "" if purchases else "先に仕入管理で箱を保存してください",
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


def create_app() -> FastAPI:
    return app


def main() -> None:
    import uvicorn

    uvicorn.run(
        "route_web.app:app",
        host="0.0.0.0",
        port=ROUTE_WEB_PORT,
        reload=False,
    )


if __name__ == "__main__":
    main()

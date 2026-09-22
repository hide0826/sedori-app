# -*- coding: utf-8 -*-
"""ルート時刻入力 FastAPI（:8792）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from route_web import ROUTE_WEB_PORT
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
INDEX_PATH = STATIC_DIR / "index.html"

app = FastAPI(title="HIRIO Route Web", version="0.1.5")


def _page_html(web_id: str) -> str:
    if not PAGE_PATH.is_file():
        raise HTTPException(status_code=500, detail="route.html missing")
    html = PAGE_PATH.read_text(encoding="utf-8")
    return html.replace("__WEB_ID__", web_id)


def _index_html() -> str:
    if not INDEX_PATH.is_file():
        raise HTTPException(status_code=500, detail="index.html missing")
    return INDEX_PATH.read_text(encoding="utf-8")


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "service": "route_web"}


@app.get("/", response_class=HTMLResponse)
def index_page() -> HTMLResponse:
    """固定URL。スマホはこのページだけブックマークすればよい。"""
    return HTMLResponse(_index_html())


@app.get("/api/routes")
def api_routes() -> JSONResponse:
    return JSONResponse({"routes": list_route_summaries()})


@app.get("/route/{web_id}", response_class=HTMLResponse)
def route_page(web_id: str) -> HTMLResponse:
    doc = load_route_json(web_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"route not found: {web_id}")
    return HTMLResponse(_page_html(web_id))


@app.get("/api/route/{web_id}")
def get_route(web_id: str) -> JSONResponse:
    doc = load_route_json(web_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"route not found: {web_id}")
    return JSONResponse(doc)


@app.put("/api/route/{web_id}")
def put_route(web_id: str, body: Dict[str, Any]) -> JSONResponse:
    existing = load_route_json(web_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"route not found: {web_id}")
    body = dict(body)
    body["web_id"] = web_id
    body["folder_path"] = existing.get("folder_path") or body.get("folder_path")
    body["schema_version"] = existing.get("schema_version") or 1
    body = stamp_updated(body)
    save_route_json(web_id, body)
    return JSONResponse(body)


@app.post("/api/route/{web_id}/stores/{store_code}/receipts")
async def upload_receipt(
    web_id: str,
    store_code: str,
    file: UploadFile = File(...),
) -> JSONResponse:
    doc = load_route_json(web_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"route not found: {web_id}")
    folder = resolve_folder(web_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="folder missing")
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
    folder = resolve_folder(web_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="folder missing")
    # パストラバーサル防止
    name = Path(filename).name
    path = receipt_dir(folder) / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path)


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

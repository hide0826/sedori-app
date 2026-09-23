# -*- coding: utf-8 -*-
"""ネット仕入のメルカリ証憑を、ログイン済みのChromeで撮影して行へ保存する。"""
from __future__ import annotations

import base64
import json
import os
import secrets
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from services.flea_market_evidence_ocr import (
    is_delivery_label_name,
    parse_transaction_ocr_text,
)
from services.flea_market_evidence_service import (
    record_fields_from_save,
    save_evidence_bundle,
)
from services.mercari_evidence_capture import normalize_mercari_item_url

_EXTENSION_DIR = Path(__file__).resolve().parents[2] / "mercari_capture_extension"


def _chrome_executable() -> Optional[str]:
    local = os.environ.get("LOCALAPPDATA", "")
    program = os.environ.get("PROGRAMFILES", "")
    program_x86 = os.environ.get("PROGRAMFILES(X86)", "")
    for base in (program, program_x86, local):
        if not base:
            continue
        path = Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"
        if path.is_file():
            return str(path)
    return None


class _MercariCaptureThread(QThread):
    login_needed = Signal()
    status = Signal(str)
    done = Signal(object)
    failed = Signal(str)
    need_extension = Signal(str)

    def __init__(self, jobs: List[Dict[str, Any]], evidence_root: str):
        super().__init__()
        self.jobs = jobs
        self.evidence_root = evidence_root
        self._lock = threading.Lock()
        self._control = "wait"
        self._hello = threading.Event()
        self._incoming: List[Dict[str, Any]] = []
        self._token = secrets.token_urlsafe(16)
        self._server: Optional[ThreadingHTTPServer] = None

    def resume_after_login(self) -> None:
        with self._lock:
            self._control = "continue"

    def abort_login(self) -> None:
        with self._lock:
            self._control = "abort"

    def _take_control(self) -> str:
        with self._lock:
            action = self._control
            if action != "wait":
                self._control = "wait"
            return action

    def run(self) -> None:
        chrome = _chrome_executable()
        if not chrome:
            self.failed.emit("Google Chrome が見つかりません。")
            return
        handler = self._make_handler()
        try:
            self._server = ThreadingHTTPServer(("127.0.0.1", 8765), handler)
        except OSError as exc:
            self.failed.emit(f"撮影の待受を開始できませんでした。\n{exc}")
            return
        server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        server_thread.start()
        url = "http://127.0.0.1:8765/go"
        try:
            subprocess.Popen([chrome, url])
        except OSError as exc:
            self._shutdown()
            self.failed.emit(f"いまのChromeを開けませんでした。\n{exc}")
            return
        if not self._hello.wait(8):
            self._shutdown()
            self.need_extension.emit(str(_EXTENSION_DIR))
            return
        results = self._collect_results()
        self._shutdown()
        self.done.emit(results)

    def _shutdown(self) -> None:
        server = self._server
        self._server = None
        if server is not None:
            try:
                server.shutdown()
            except Exception:
                pass

    def _collect_results(self) -> List[Dict[str, Any]]:
        by_id = {str(index): job for index, job in enumerate(self.jobs)}
        pending = set(by_id)
        results: List[Dict[str, Any]] = []
        deadline = time.time() + max(90, 90 * len(self.jobs))
        while pending and time.time() < deadline:
            item = None
            with self._lock:
                if self._incoming:
                    item = self._incoming.pop(0)
            if item is None:
                time.sleep(0.2)
                continue
            status = str(item.get("status") or "")
            if status == "finished":
                break
            if status == "login":
                self.login_needed.emit()
                continue
            job_id = str(item.get("id") or "")
            job = by_id.get(job_id)
            if job is None:
                message = str(item.get("message") or "").strip()
                if status in ("error", "stopped") and message:
                    results.append({
                        "title": "",
                        "error": message,
                        "stopped": status == "stopped",
                    })
                    break
                continue
            pending.discard(job_id)
            title = str(job.get("title") or "")
            self.status.emit(f"情報撮影: {title[:24]}")
            if status == "stopped":
                results.append({**job, "stopped": True, "error": item.get("message") or "中止しました。"})
                break
            if status != "ok":
                results.append({**job, "error": item.get("message") or "撮影に失敗しました。"})
                continue
            paths = self._write_images(item.get("images") or [])
            if len(paths) < 3:
                results.append({**job, "error": "3枚そろいませんでした。"})
                continue
            fields = self._save_job(job, paths)
            results.append({**job, "fields": fields})
            for path in paths:
                try:
                    Path(path).unlink(missing_ok=True)
                except OSError:
                    pass
        if pending and not any(item.get("stopped") for item in results):
            results.append({
                "title": "",
                "error": (
                    "Chromeから撮影結果が届きませんでした。\n"
                    "chrome://extensions で「HIRIO メルカリ撮影」の再読み込みを押してから、もう一度試してください。"
                ),
            })
        return results

    def _write_images(self, images: List[str]) -> List[str]:
        paths: List[str] = []
        for raw in images[:3]:
            text = str(raw or "")
            if "," in text and text.strip().startswith("data:"):
                text = text.split(",", 1)[1]
            try:
                blob = base64.b64decode(text)
            except Exception:
                continue
            handle, name = tempfile.mkstemp(prefix="hirio_mercari_", suffix=".png")
            os.close(handle)
            Path(name).write_bytes(blob)
            paths.append(name)
        return paths

    def _make_handler(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args) -> None:
                return

            def _json(self, code: int, payload: Dict[str, Any]) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _read_json(self) -> Dict[str, Any]:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    data = json.loads(raw.decode("utf-8"))
                except Exception:
                    return {}
                return data if isinstance(data, dict) else {}

            def _token_ok(self, token: str) -> bool:
                return token == owner._token

            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path == "/go":
                    jobs = [
                        {"id": str(index), "url": job["url"]}
                        for index, job in enumerate(owner.jobs)
                    ]
                    payload = json.dumps({
                        "baseUrl": "http://127.0.0.1:8765",
                        "token": owner._token,
                        "jobs": jobs,
                    }).replace("<", "\\u003c")
                    html = (
                        "<!doctype html><meta charset='utf-8'><title>HIRIO 情報撮影</title>"
                        "<p id='status'>HIRIOの拡張機能を待っています。</p>"
                        f"<script id='hirio-jobs' type='application/json'>{payload}</script>"
                    ).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(html)))
                    self.end_headers()
                    self.wfile.write(html)
                    return
                if parsed.path == "/control":
                    token = parse_qs(parsed.query).get("token", [""])[0]
                    if not self._token_ok(token):
                        self._json(403, {"action": "abort"})
                        return
                    self._json(200, {"action": owner._take_control()})
                    return
                self._json(404, {})

            def do_POST(self) -> None:
                data = self._read_json()
                if not self._token_ok(str(data.get("token") or "")):
                    self._json(403, {"ok": False})
                    return
                path = urlparse(self.path).path
                if path == "/hello":
                    owner._hello.set()
                    self._json(200, {"ok": True})
                    return
                if path == "/result":
                    with owner._lock:
                        owner._incoming.append(data)
                    self._json(200, {"ok": True})
                    return
                self._json(404, {})

        return Handler

    def _save_job(self, job: Dict[str, Any], paths: List[str]) -> Dict[str, str]:
        try:
            result = save_evidence_bundle(
                root=self.evidence_root,
                purchase_datetime=job.get("purchase_datetime"),
                store_value=job.get("store_value") or "メルカリ",
                asin=job.get("asin"),
                slot_sources=paths,
                flea_markets=None,
                upload_to_gcs=True,
            )
            fields = record_fields_from_save(result)
        except Exception as exc:
            return {"_error": str(exc)}
        try:
            from services.ocr_service import OCRService

            text = str(OCRService().extract_text(paths[2]).get("text") or "")
            parsed = parse_transaction_ocr_text(text)
            if parsed.item_id and not str(job.get("transaction_id") or "").strip():
                fields["取引ID"] = parsed.item_id
            if parsed.seller_name and (
                not str(job.get("seller_name") or "").strip()
                or is_delivery_label_name(str(job.get("seller_name") or ""))
            ):
                fields["ユーザー名"] = parsed.seller_name
        except Exception:
            pass
        return fields


class InventoryMercariCaptureMixin:
    def capture_mercari_listing_evidence(self) -> None:
        """出品URLがあるメルカリ行を撮影し、証憑列へ保存する。"""
        if getattr(self, "purchase_mode", "store") != "online":
            return
        if getattr(self, "_mercari_capture_thread", None) is not None and self._mercari_capture_thread.isRunning():
            QMessageBox.information(self, "情報撮影", "いま撮影中です。")
            return
        data = getattr(self, "filtered_data", None)
        if data is None or len(data) == 0:
            QMessageBox.information(self, "情報撮影", "仕入データがありません。")
            return
        jobs = self._mercari_capture_jobs()
        if not jobs:
            QMessageBox.information(
                self,
                "情報撮影",
                "メルカリの出品URLがある行がありません。\n"
                "出品URLに https://jp.mercari.com/item/m... を入れてください。\n"
                "ヤフオクは、まだ撮影できません。",
            )
            return
        root = self._mercari_evidence_root()
        if not root:
            return
        answer = QMessageBox.question(
            self,
            "情報撮影",
            f"メルカリ {len(jobs)} 件を撮影して、各行の証憑に保存します。\n"
            "いま開いている、ログイン済みのChromeで撮ります。\n"
            "最初の1回だけ、Chromeに拡張機能を入れる案内が出ます。",
        )
        if answer != QMessageBox.Yes:
            return
        thread = _MercariCaptureThread(jobs, root)
        thread.login_needed.connect(self._on_mercari_login_needed)
        thread.status.connect(self._on_mercari_capture_status)
        thread.done.connect(self._on_mercari_capture_done)
        thread.failed.connect(self._on_mercari_capture_failed)
        thread.need_extension.connect(self._on_mercari_need_extension)
        self._mercari_capture_thread = thread
        button = getattr(self, "info_capture_btn", None)
        if button is not None:
            button.setEnabled(False)
        thread.start()

    def _mercari_capture_jobs(self) -> List[Dict[str, Any]]:
        data = self.filtered_data
        table = getattr(self, "data_table", None)
        positions: List[int] = []
        if table is not None and table.selectionModel() is not None:
            positions = sorted({index.row() for index in table.selectionModel().selectedRows()})
        if not positions:
            positions = list(range(len(data)))
        jobs: List[Dict[str, Any]] = []
        for pos in positions:
            if pos < 0 or pos >= len(data):
                continue
            row = data.iloc[pos]
            url = normalize_mercari_item_url(row.get("出品URL"))
            if not url:
                continue
            label = data.index[pos]
            jobs.append({
                "index": label,
                "url": url,
                "title": str(row.get("商品名") or ""),
                "asin": str(row.get("ASIN") or ""),
                "purchase_datetime": str(row.get("仕入れ日") or ""),
                "store_value": str(row.get("仕入チャネル") or row.get("仕入先") or "メルカリ"),
                "transaction_id": str(row.get("取引ID") or ""),
                "seller_name": str(row.get("ユーザー名") or ""),
            })
        return jobs

    def _mercari_evidence_root(self) -> str:
        try:
            from utils.settings_helper import (
                get_purchase_evidence_local_root,
                set_purchase_evidence_local_root,
            )
        except ImportError:
            from desktop.utils.settings_helper import (  # type: ignore
                get_purchase_evidence_local_root,
                set_purchase_evidence_local_root,
            )
        root = get_purchase_evidence_local_root()
        if root:
            return root
        picked = QFileDialog.getExistingDirectory(self, "仕入証憑の保存先フォルダを選択")
        if not picked:
            QMessageBox.warning(self, "情報撮影", "保存先フォルダを選んでください。")
            return ""
        set_purchase_evidence_local_root(picked)
        return picked

    def _on_mercari_capture_status(self, text: str) -> None:
        try:
            self._update_workflow_status(text, emphasize=True)
            QApplication.processEvents()
        except Exception:
            pass

    def _on_mercari_login_needed(self) -> None:
        thread = getattr(self, "_mercari_capture_thread", None)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("情報撮影")
        box.setText(
            "メルカリのログインが切れています。\n"
            "いま開いているChromeでログインしてから「続ける」を押してください。"
        )
        continue_btn = box.addButton("続ける", QMessageBox.AcceptRole)
        box.addButton("中止", QMessageBox.RejectRole)
        box.exec()
        if thread is None:
            return
        if box.clickedButton() is continue_btn:
            thread.resume_after_login()
        else:
            thread.abort_login()

    def _finish_mercari_capture_ui(self) -> None:
        button = getattr(self, "info_capture_btn", None)
        if button is not None:
            button.setEnabled(True)

    def _on_mercari_need_extension(self, folder: str) -> None:
        self._finish_mercari_capture_ui()
        QMessageBox.information(
            self,
            "情報撮影",
            "いまのChromeで撮るには、拡張機能を一度入れます。\n\n"
            "1. Chromeで chrome://extensions を開く\n"
            "2. 右上の「デベロッパーモード」をオン\n"
            "3. 「パッケージ化されていない拡張機能を読み込む」\n"
            "4. 次のフォルダを選ぶ\n"
            f"{folder}\n"
            "5. もう一度「情報撮影」を押す",
        )

    def _on_mercari_capture_failed(self, message: str) -> None:
        self._finish_mercari_capture_ui()
        QMessageBox.warning(self, "情報撮影", message or "撮影に失敗しました。")

    def _on_mercari_capture_done(self, results: object) -> None:
        self._finish_mercari_capture_ui()
        rows = list(results or [])
        saved = 0
        errors: List[str] = []
        stopped = False
        for item in rows:
            if item.get("stopped"):
                stopped = True
                if item.get("error"):
                    errors.append(str(item.get("error")))
                continue
            fields = item.get("fields") or {}
            if fields.get("_error"):
                errors.append(f"{item.get('title') or item.get('url')}: {fields.get('_error')}")
                continue
            if item.get("error"):
                errors.append(f"{item.get('title') or item.get('url')}: {item.get('error')}")
                continue
            self._write_mercari_fields(item.get("index"), fields)
            saved += 1
        if saved:
            try:
                self.update_table()
            except Exception:
                pass
        lines = [f"保存しました: {saved} 件"]
        if stopped:
            lines.append("ログインが完了しなかったため、残りは撮っていません。")
        if errors:
            lines.append("失敗:")
            lines.extend(errors[:8])
        QMessageBox.information(self, "情報撮影", "\n".join(lines))

    def _write_mercari_fields(self, label: Any, fields: Dict[str, str]) -> None:
        for frame_name in ("filtered_data", "inventory_data"):
            frame = getattr(self, frame_name, None)
            if frame is None or label not in getattr(frame, "index", []):
                continue
            for col, value in fields.items():
                if not col or col.startswith("_"):
                    continue
                if col not in frame.columns:
                    frame[col] = ""
                frame.at[label, col] = value or ""

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SP-API テスト用ウィジェット

.env の以下3項目を使って簡易テストを行う:
- SP_API_CLIENT_ID
- SP_API_CLIENT_SECRET
- SP_API_REFRESH_TOKEN
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import requests
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QLineEdit,
    QTextEdit,
    QMessageBox,
)


class SPAPITestWidget(QWidget):
    """SP-API の接続確認を行うテストタブ。"""

    LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"
    SP_API_ENDPOINT = "https://sellingpartnerapi-fe.amazon.com/sellers/v1/marketplaceParticipations"
    CATALOG_API_ENDPOINT_TEMPLATE = "https://sellingpartnerapi-fe.amazon.com/catalog/2022-04-01/items/{asin}"
    MARKETPLACE_ID_JP = "A1VC38T7YXB528"

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._last_access_token: str = ""
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        summary_group = QGroupBox("SP-API テスト（LWA認証のみ）")
        summary_layout = QVBoxLayout(summary_group)
        summary_layout.addWidget(QLabel("対象マーケットプレイス: JP (A1VC38T7YXB528)"))
        summary_layout.addWidget(QLabel("テスト手順: .env読込確認 -> LWAトークン取得 -> SP-API疎通確認"))
        layout.addWidget(summary_group)

        button_layout = QHBoxLayout()
        self.check_env_btn = QPushButton(".env 設定確認")
        self.check_env_btn.clicked.connect(self.on_check_env_clicked)
        button_layout.addWidget(self.check_env_btn)

        self.get_token_btn = QPushButton("LWAトークン取得")
        self.get_token_btn.clicked.connect(self.on_get_token_clicked)
        button_layout.addWidget(self.get_token_btn)

        self.test_sp_api_btn = QPushButton("SP-API 接続テスト")
        self.test_sp_api_btn.clicked.connect(self.on_test_sp_api_clicked)
        button_layout.addWidget(self.test_sp_api_btn)

        self.clear_log_btn = QPushButton("ログクリア")
        button_layout.addWidget(self.clear_log_btn)
        button_layout.addStretch()
        layout.addLayout(button_layout)

        asin_test_layout = QHBoxLayout()
        asin_test_layout.addWidget(QLabel("ASIN:"))
        self.asin_input = QLineEdit()
        self.asin_input.setPlaceholderText("例: B00007B4DM")
        asin_test_layout.addWidget(self.asin_input, 1)
        self.test_catalog_btn = QPushButton("Catalog API 1件テスト")
        self.test_catalog_btn.clicked.connect(self.on_test_catalog_api_clicked)
        asin_test_layout.addWidget(self.test_catalog_btn)
        layout.addLayout(asin_test_layout)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setLineWrapMode(QTextEdit.NoWrap)
        self.log_output.setPlaceholderText("ここにテストログが表示されます。")
        layout.addWidget(self.log_output)
        self.clear_log_btn.clicked.connect(self.log_output.clear)

        self._append_log("SP-APIテストタブを初期化しました。")

    def _project_root(self) -> Path:
        # python/desktop/ui/sp_api_test_widget.py -> プロジェクトルート
        return Path(__file__).resolve().parents[3]

    def _env_path(self) -> Path:
        return self._project_root() / ".env"

    def _load_env_file(self) -> Dict[str, str]:
        env_path = self._env_path()
        if not env_path.exists():
            return {}

        env_map: Dict[str, str] = {}
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env_map[key.strip()] = value.strip()
        return env_map

    @staticmethod
    def _mask_secret(value: str) -> str:
        if not value:
            return "(未設定)"
        if len(value) <= 8:
            return "*" * len(value)
        return f"{value[:4]}...{value[-4:]}"

    def _append_log(self, text: str) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        self.log_output.append(f"[{now}] {text}")

    def _read_credentials(self) -> Dict[str, str]:
        env_map = self._load_env_file()
        return {
            "client_id": env_map.get("SP_API_CLIENT_ID", ""),
            "client_secret": env_map.get("SP_API_CLIENT_SECRET", ""),
            "refresh_token": env_map.get("SP_API_REFRESH_TOKEN", ""),
        }

    def on_check_env_clicked(self) -> None:
        creds = self._read_credentials()
        self._append_log(".env を確認します。")
        self._append_log(f"- SP_API_CLIENT_ID: {self._mask_secret(creds['client_id'])}")
        self._append_log(f"- SP_API_CLIENT_SECRET: {self._mask_secret(creds['client_secret'])}")
        self._append_log(f"- SP_API_REFRESH_TOKEN: {self._mask_secret(creds['refresh_token'])}")

        missing = [k for k, v in creds.items() if not v]
        if missing:
            QMessageBox.warning(
                self,
                "設定不足",
                "以下の値が未設定です:\n- " + "\n- ".join(missing),
            )
            return
        QMessageBox.information(self, "設定確認", ".env の必須3項目は設定されています。")

    def _request_lwa_access_token(self) -> str:
        creds = self._read_credentials()
        missing = [name for name, value in creds.items() if not value]
        if missing:
            raise ValueError("未設定の項目: " + ", ".join(missing))

        payload = {
            "grant_type": "refresh_token",
            "refresh_token": creds["refresh_token"],
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
        }
        response = requests.post(self.LWA_TOKEN_URL, data=payload, timeout=30)
        response.raise_for_status()
        body = response.json()
        access_token = body.get("access_token", "")
        if not access_token:
            raise RuntimeError("LWAレスポンスに access_token がありません。")
        return access_token

    def on_get_token_clicked(self) -> None:
        self._append_log("LWAトークン取得を開始します。")
        try:
            access_token = self._request_lwa_access_token()
            self._last_access_token = access_token
            self._append_log("LWAトークン取得成功。")
            self._append_log(f"アクセストークン: {self._mask_secret(access_token)}")
            QMessageBox.information(self, "成功", "LWAトークンの取得に成功しました。")
        except Exception as e:
            self._append_log(f"LWAトークン取得失敗: {e}")
            QMessageBox.critical(self, "エラー", f"LWAトークン取得に失敗しました:\n{e}")

    def on_test_sp_api_clicked(self) -> None:
        self._append_log("SP-API接続テストを開始します。")
        try:
            access_token = self._last_access_token or self._request_lwa_access_token()
            headers = self._build_common_headers(access_token)

            response = requests.get(self.SP_API_ENDPOINT, headers=headers, timeout=30)
            status = response.status_code
            self._append_log(f"HTTPステータス: {status}")

            try:
                body = response.json()
            except Exception:
                body = {"raw": response.text}

            self._append_log("レスポンス:")
            self._append_log(json.dumps(body, ensure_ascii=False, indent=2))

            if response.ok:
                participations = body.get("payload", [])
                jp_enabled = any(
                    p.get("marketplace", {}).get("id") == self.MARKETPLACE_ID_JP
                    for p in participations
                )
                msg = "SP-API接続テスト成功。"
                if jp_enabled:
                    msg += "\nJPマーケットプレイス参加情報を確認できました。"
                else:
                    msg += "\nJPマーケットプレイス情報はレスポンス内で確認できませんでした。"
                QMessageBox.information(self, "接続テスト結果", msg)
            else:
                QMessageBox.warning(
                    self,
                    "接続テスト結果",
                    f"SP-API呼び出しは失敗しました（HTTP {status}）。\nログを確認してください。",
                )
        except Exception as e:
            self._append_log(f"SP-API接続テスト失敗: {e}")
            QMessageBox.critical(self, "エラー", f"SP-API接続テストに失敗しました:\n{e}")

    def _build_common_headers(self, access_token: str) -> Dict[str, str]:
        return {
            "x-amz-access-token": access_token,
            "x-amz-date": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            "user-agent": "HIRIO-SPAPITest/1.0 (Language=Python)",
            "accept": "application/json",
        }

    def on_test_catalog_api_clicked(self) -> None:
        asin = (self.asin_input.text() or "").strip().upper()
        if not asin:
            QMessageBox.warning(self, "入力不足", "ASIN を入力してください。")
            return
        if len(asin) != 10:
            QMessageBox.warning(self, "形式エラー", "ASIN は10文字で入力してください。")
            return

        self._append_log(f"Catalog API 1件テストを開始します。ASIN={asin}")
        try:
            access_token = self._last_access_token or self._request_lwa_access_token()
            headers = self._build_common_headers(access_token)
            endpoint = self.CATALOG_API_ENDPOINT_TEMPLATE.format(asin=asin)
            params = {
                "marketplaceIds": self.MARKETPLACE_ID_JP,
                "includedData": "summaries,attributes,identifiers,images,salesRanks",
            }

            response = requests.get(endpoint, headers=headers, params=params, timeout=30)
            status = response.status_code
            self._append_log(f"Catalog API HTTPステータス: {status}")

            try:
                body = response.json()
            except Exception:
                body = {"raw": response.text}

            self._append_log("Catalog API レスポンス:")
            self._append_log(json.dumps(body, ensure_ascii=False, indent=2))

            if response.ok:
                title = ""
                summaries = body.get("summaries", [])
                if summaries and isinstance(summaries, list):
                    title = summaries[0].get("itemName", "") or ""
                message = "Catalog API テスト成功。"
                if title:
                    message += f"\n商品名: {title}"
                QMessageBox.information(self, "Catalog API テスト結果", message)
            else:
                QMessageBox.warning(
                    self,
                    "Catalog API テスト結果",
                    f"Catalog API 呼び出しは失敗しました（HTTP {status}）。\nログを確認してください。",
                )
        except Exception as e:
            self._append_log(f"Catalog API テスト失敗: {e}")
            QMessageBox.critical(self, "エラー", f"Catalog API テストに失敗しました:\n{e}")

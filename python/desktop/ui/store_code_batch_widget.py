#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
店舗コード移行バッチウィジェット

- 店舗マスタ（storesテーブル）の店舗コード(store_code)を一括付与
- 現在の店舗マスタの状況（件数・store_code未設定件数など）を確認

※ 想定用途: 来年度本番運用前の一括メンテナンス用
"""

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QMessageBox,
    QGroupBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor

from typing import Dict, Any

from database.store_db import StoreDatabase


class StoreCodeBatchWidget(QWidget):
    """店舗コード(store_code)移行用バッチウィジェット"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = StoreDatabase()
        self._setup_ui()
        self.refresh_summary()

    # ===== UI構築 =====
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 説明エリア
        desc_group = QGroupBox("店舗コード移行バッチ（概要）")
        desc_layout = QVBoxLayout(desc_group)
        desc_label = QLabel(
            "店舗マスタの「店舗コード(store_code)」を自動付与し、来年度以降は\n"
            "店舗を識別するキーとして store_code をメインで利用するための準備を行います。\n\n"
            "※ 注意事項\n"
            "- 既存データ（仕入れ先コードなど）は将来用の参考情報として残りますが、\n"
            "  新しい機能では store_code を優先して参照するようにコードを変更します。\n"
            "- バッチ実行前に、必ず hirio.db のバックアップを取得してください。"
        )
        desc_label.setWordWrap(True)
        desc_layout.addWidget(desc_label)
        layout.addWidget(desc_group)

        # 操作ボタン
        btn_group = QGroupBox("バッチ操作")
        btn_layout = QHBoxLayout(btn_group)

        self.btn_refresh = QPushButton("店舗マスタ状況を再読込")
        self.btn_refresh.clicked.connect(self.refresh_summary)
        btn_layout.addWidget(self.btn_refresh)

        self.btn_assign_codes = QPushButton("店舗コード一括付与（store_code 再付番）")
        self.btn_assign_codes.clicked.connect(self.run_assign_store_codes)
        btn_layout.addWidget(self.btn_assign_codes)

        btn_layout.addStretch()
        layout.addWidget(btn_group)

        # サマリ・ログ表示
        self.summary_label = QLabel("店舗マスタ状況: 取得中...")
        layout.addWidget(self.summary_label)

        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setStyleSheet("font-family: Consolas, 'Courier New', monospace; font-size: 11px;")
        layout.addWidget(self.log_edit, stretch=1)

    # ===== サマリ表示 =====
    def refresh_summary(self) -> None:
        """店舗マスタの現在の状況を表示"""
        try:
            conn = self.db._get_connection()  # 既存の接続ユーティリティを利用
            cur = conn.cursor()

            # 総件数
            cur.execute("SELECT COUNT(*) FROM stores")
            total = cur.fetchone()[0]

            # store_code 未設定件数
            cur.execute("SELECT COUNT(*) FROM stores WHERE store_code IS NULL OR store_code = ''")
            no_store_code = cur.fetchone()[0]

            # supplier_code 未設定件数（参考）
            cur.execute("SELECT COUNT(*) FROM stores WHERE supplier_code IS NULL OR supplier_code = ''")
            no_supplier_code = cur.fetchone()[0]

            self.summary_label.setText(
                f"店舗マスタ状況: 総店舗数 {total} 件 / "
                f"store_code 未設定 {no_store_code} 件 / "
                f"supplier_code 未設定 {no_supplier_code} 件"
            )

            self._append_log(
                f"[INFO] 店舗マスタ状況を更新しました: total={total}, "
                f"no_store_code={no_store_code}, no_supplier_code={no_supplier_code}"
            )
        except Exception as e:
            self.summary_label.setText(f"店舗マスタ状況: 取得エラー ({e})")
            self._append_log(f"[ERROR] 店舗マスタ状況の取得に失敗しました: {e}")

    # ===== バッチ処理本体 =====
    def run_assign_store_codes(self) -> None:
        """stores テーブルで store_code が空のレコードに自動で店舗コードを付与"""
        reply = QMessageBox.question(
            self,
            "確認",
            "店舗マスタの store_code が空の店舗に対して、自動で店舗コードを付与します。\n"
            "（チェーン店コードマッピングを参照して連番を生成します）\n\n"
            "※ 実行前に hirio.db のバックアップを取得していることを確認してください。\n\n"
            "バッチ処理を実行しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            self._append_log("[INFO] 店舗コード一括付与はユーザーによりキャンセルされました。")
            return

        try:
            self._append_log("[INFO] 店舗コード一括付与を開始します...")
            result: Dict[str, Any] = self.db.assign_store_codes_to_empty_stores()
            total = result.get("total", 0)
            updated = result.get("updated", 0)
            errors = result.get("errors", 0)

            msg = (
                f"店舗コード一括付与が完了しました。\n\n"
                f"対象: {total} 件\n"
                f"更新成功: {updated} 件\n"
                f"エラー: {errors} 件"
            )
            QMessageBox.information(self, "店舗コード一括付与完了", msg)
            self._append_log(
                f"[INFO] 店舗コード一括付与完了: total={total}, updated={updated}, errors={errors}"
            )
            self.refresh_summary()
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"店舗コード一括付与中にエラーが発生しました:\n{e}")
            self._append_log(f"[ERROR] 店舗コード一括付与中にエラーが発生しました: {e}")

    # ===== ログユーティリティ =====
    def _append_log(self, message: str) -> None:
        """ログ欄に1行追記"""
        self.log_edit.append(message)
        # 常に末尾にスクロール
        cursor = self.log_edit.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_edit.setTextCursor(cursor)



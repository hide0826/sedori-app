#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基礎データ取得タブ

将来的に Amazon レポートや SP-API から
出品日・在庫情報などの基礎データを取得するためのタブ。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QSettings, QUrl
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QLineEdit,
    QFileDialog,
    QTextEdit,
    QMessageBox,
    QTabWidget,
)
from PySide6.QtGui import QDesktopServices

from utils.settings_helper import is_pro_enabled
from desktop.database.product_db import ProductDatabase
from desktop.database.purchase_db import PurchaseDatabase
from desktop.database.sales_db import SalesDatabase

import pandas as pd
from pathlib import Path
from typing import Dict


class DataAcquisitionWidget(QWidget):
    """基礎データ取得ウィジェット（ひな形）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("HIRIO", "SedoriDesktopApp")
        self.product_db = ProductDatabase()
        self.purchase_db = PurchaseDatabase()
        self.sales_db = SalesDatabase()
        self.setup_ui()

    def setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # PRO版チェック
        if not is_pro_enabled():
            locked_label = QLabel(
                "この機能は PRO 版専用です。\n"
                "設定タブで PRO 版を有効にすると利用できます。"
            )
            locked_label.setAlignment(Qt.AlignCenter)
            locked_label.setStyleSheet("color: #cccccc; font-size: 14px;")
            layout.addWidget(locked_label)
            return

        intro = QLabel(
            "Amazonレポートや将来のSP-APIから、価格改定や在庫管理に必要な\n"
            "基礎データ（FBA在庫受領日・出品日など）を取得するタブです。"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)

        self.setup_listing_report_tab()
        self.setup_transaction_report_tab()

    # --- 在庫元帳タブ（FBA在庫受領日ナビ付き） ---
    def setup_listing_report_tab(self) -> None:
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(10, 10, 10, 10)
        tab_layout.setSpacing(8)

        # 在庫受領日取得の最短ナビ（解説テキスト）
        guide_group = QGroupBox("「在庫受領日」取得の最短ナビ")
        guide_layout = QVBoxLayout(guide_group)
        guide_text = QLabel(
            "1. メニューを開く\n"
            "   [レポート] ＞ [フルフィルメント] を選択。\n\n"
            "2. レポートの種類を選択\n"
            "   左メニュー [在庫] セクションの一番上、「在庫元帳」をクリック。\n\n"
            "3. 「ダウンロード」タブへ切り替え\n"
            "   画面中央のタブを [オンラインで閲覧] から [ダウンロード] に切り替える。\n\n"
            "4. 詳細条件を設定（最重要）\n"
            "   ・レポートのタイプ: 「詳細表示」を選択。\n"
            "   ・イベントタイプ: 「受領」を選択（倉庫に入った日だけが抽出されます）。\n"
            "   ・期間: 「過去30日間」など、対象の仕入れ時期が含まれる期間を指定。\n\n"
            "5. リクエスト実行\n"
            "   [.csv形式でのダウンロードをリクエスト] をクリック。\n\n"
            "6. 完了・保存\n"
            "   下の表のステータスが「完了」になったら [ダウンロード]。"
        )
        guide_text.setWordWrap(True)
        guide_layout.addWidget(guide_text)
        tab_layout.addWidget(guide_group)

        # 在庫元帳レポートのURL設定＆起動ボタン
        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel("在庫元帳レポートURL:"))

        self.ledger_url_edit = QLineEdit()
        self.ledger_url_edit.setPlaceholderText("在庫元帳レポートのURL")
        url_layout.addWidget(self.ledger_url_edit, 1)

        open_url_btn = QPushButton("ブラウザで開く")
        open_url_btn.clicked.connect(self._open_ledger_url)
        url_layout.addWidget(open_url_btn)

        tab_layout.addLayout(url_layout)

        # デフォルトフォルダ
        folder_group = QGroupBox("在庫元帳CSVのフォルダ設定")
        folder_layout = QHBoxLayout(folder_group)

        folder_layout.addWidget(QLabel("デフォルトフォルダ:"))

        self.listing_default_dir_edit = QLineEdit()
        self.listing_default_dir_edit.setReadOnly(True)
        self.listing_default_dir_edit.setPlaceholderText("未設定")
        folder_layout.addWidget(self.listing_default_dir_edit, 1)

        browse_btn = QPushButton("デフォルト設定")
        browse_btn.clicked.connect(self._browse_listing_default_dir)
        folder_layout.addWidget(browse_btn)

        tab_layout.addWidget(folder_group)

        # ファイル選択ボタン
        file_button_layout = QHBoxLayout()

        self.listing_file_edit = QLineEdit()
        self.listing_file_edit.setPlaceholderText("在庫元帳レポートCSVのパス（ドラッグ＆ドロップも可）")
        self.listing_file_edit.setReadOnly(True)
        file_button_layout.addWidget(self.listing_file_edit, 1)

        select_btn = QPushButton("ファイル読込")
        select_btn.clicked.connect(self._select_listing_file)
        file_button_layout.addWidget(select_btn)

        tab_layout.addLayout(file_button_layout)

        # ドラッグ＆ドロップエリア
        self.drop_area = QTextEdit()
        self.drop_area.setAcceptDrops(True)
        self.drop_area.setReadOnly(True)
        self.drop_area.setPlaceholderText(
            "ここに Amazon 在庫元帳レポート (CSV/TSV/TXT) をドラッグ＆ドロップしてください。\n"
            "SKU から出品日（受領日など）を特定し、商品DB／仕入DB の listed_date を自動更新します。"
        )
        # ドロップハンドラをこのクラスのメソッドに委譲するためのフラグ
        self.drop_area.installEventFilter(self)
        tab_layout.addWidget(self.drop_area, 1)

        # 実行ボタン
        run_btn = QPushButton("出品日をDBに反映")
        run_btn.setStyleSheet("background-color: #28a745; color: white; font-weight: bold;")
        run_btn.clicked.connect(self._run_listing_import)
        tab_layout.addWidget(run_btn)

        # ログ表示
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        tab_layout.addWidget(self.log_edit, 1)

        # URL・デフォルトフォルダをロード
        self._load_ledger_url()
        self._load_listing_default_dir()

        self.tab_widget.addTab(tab, "在庫元帳")

    # --- トランザクションタブ（販売DB取り込み） ---
    def setup_transaction_report_tab(self) -> None:
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(10, 10, 10, 10)
        tab_layout.setSpacing(8)

        # トランザクションレポート取得の最短ナビ
        guide_group = QGroupBox("「トランザクションレポート」取得の最短ナビ")
        guide_layout = QVBoxLayout(guide_group)
        guide_text = QLabel(
            "検索窓（おすすめ）:\n"
            " 画面中央上部の検索窓に「レポートリポジトリ」と入力してエンターを押すと、直接リンクが表示されます。"
        )
        guide_text.setWordWrap(True)
        guide_layout.addWidget(guide_text)
        tab_layout.addWidget(guide_group)

        # トランザクションレポートのURL設定＆起動ボタン
        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel("トランザクションレポートURL:"))

        self.transaction_url_edit = QLineEdit()
        self.transaction_url_edit.setPlaceholderText("トランザクションレポートのURL")
        url_layout.addWidget(self.transaction_url_edit, 1)

        open_url_btn = QPushButton("ブラウザで開く")
        open_url_btn.clicked.connect(self._open_transaction_url)
        url_layout.addWidget(open_url_btn)

        tab_layout.addLayout(url_layout)

        # デフォルトフォルダ
        folder_group = QGroupBox("トランザクションCSVのフォルダ設定")
        folder_layout = QHBoxLayout(folder_group)

        folder_layout.addWidget(QLabel("デフォルトフォルダ:"))

        self.transaction_default_dir_edit = QLineEdit()
        self.transaction_default_dir_edit.setReadOnly(True)
        self.transaction_default_dir_edit.setPlaceholderText("未設定")
        folder_layout.addWidget(self.transaction_default_dir_edit, 1)

        browse_btn = QPushButton("デフォルト設定")
        browse_btn.clicked.connect(self._browse_transaction_default_dir)
        folder_layout.addWidget(browse_btn)

        tab_layout.addWidget(folder_group)

        # ファイル選択ボタン
        file_button_layout = QHBoxLayout()

        self.transaction_file_edit = QLineEdit()
        self.transaction_file_edit.setPlaceholderText("トランザクションレポートCSVのパス（ドラッグ＆ドロップも可）")
        self.transaction_file_edit.setReadOnly(True)
        file_button_layout.addWidget(self.transaction_file_edit, 1)

        select_btn = QPushButton("ファイル読込")
        select_btn.clicked.connect(self._select_transaction_file)
        file_button_layout.addWidget(select_btn)

        tab_layout.addLayout(file_button_layout)

        # ドラッグ＆ドロップエリア
        self.transaction_drop_area = QTextEdit()
        self.transaction_drop_area.setAcceptDrops(True)
        self.transaction_drop_area.setReadOnly(True)
        self.transaction_drop_area.setPlaceholderText(
            "ここに Amazon 月次トランザクションレポート (CSV/TSV/TXT) をドラッグ＆ドロップしてください。\n"
            "SKU・注文番号ごとの販売情報を解析し、販売DB（sales）に取り込みます。"
        )
        self.transaction_drop_area.installEventFilter(self)
        tab_layout.addWidget(self.transaction_drop_area, 1)

        # 実行ボタン
        run_btn = QPushButton("販売DBに取り込む")
        run_btn.setStyleSheet("background-color: #28a745; color: white; font-weight: bold;")
        run_btn.clicked.connect(self._run_transaction_import)
        tab_layout.addWidget(run_btn)

        # URL・デフォルトフォルダをロード
        self._load_transaction_url()
        self._load_transaction_default_dir()

        self.tab_widget.addTab(tab, "トランザクション")

    # --- 在庫元帳URL関連 ---
    def _load_ledger_url(self) -> None:
        stored = self.settings.value(
            "data_acquisition/inventory_ledger_url",
            "https://sellercentral.amazon.co.jp/reportcentral/LEDGER_REPORT/0",
            type=str,
        )
        if stored:
            self.ledger_url_edit.setText(stored)

    def _open_ledger_url(self) -> None:
        url_text = self.ledger_url_edit.text().strip()
        if not url_text:
            QMessageBox.warning(self, "URL未設定", "在庫元帳レポートのURLを入力してください。")
            return
        # 保存しておく
        self.settings.setValue("data_acquisition/inventory_ledger_url", url_text)
        QDesktopServices.openUrl(QUrl(url_text))

    # --- トランザクションURL関連 ---
    def _load_transaction_url(self) -> None:
        stored = self.settings.value(
            "data_acquisition/transaction_report_url",
            "https://sellercentral.amazon.co.jp/payments/reports-repository?ref=xx_Tool_xxxx_meldedSidebarSearch&mons_sel_mkid=amzn1.mp.o.A1VC38T7YXB528&mons_sel_mcid=amzn1.merchant.o.ANT0GRPZS3BQE&mons_sel_persist=true",
            type=str,
        )
        if stored:
            self.transaction_url_edit.setText(stored)

    def _open_transaction_url(self) -> None:
        url_text = self.transaction_url_edit.text().strip()
        if not url_text:
            QMessageBox.warning(self, "URL未設定", "トランザクションレポートのURLを入力してください。")
            return
        # 保存しておく
        self.settings.setValue("data_acquisition/transaction_report_url", url_text)
        QDesktopServices.openUrl(QUrl(url_text))

    # --- イベントフィルタ（ドラッグ＆ドロップ） ---
    def eventFilter(self, obj, event):
        if obj is self.drop_area or obj is getattr(self, "transaction_drop_area", None):
            et = event.type()
            from PySide6.QtCore import QEvent
            if et == QEvent.DragEnter:
                if event.mimeData().hasUrls():
                    event.acceptProposedAction()
                    return True
            elif et == QEvent.Drop:
                urls = event.mimeData().urls()
                if urls:
                    local_path = urls[0].toLocalFile()
                    if local_path:
                        if obj is self.drop_area:
                            self.listing_file_edit.setText(local_path)
                            self._append_log(f"[在庫元帳] ファイル選択: {local_path}")
                        else:
                            self.transaction_file_edit.setText(local_path)
                            self._append_log(f"[トランザクション] ファイル選択: {local_path}")
                event.acceptProposedAction()
                return True
        return super().eventFilter(obj, event)

    # --- デフォルトフォルダ関連 ---
    def _load_listing_default_dir(self) -> None:
        stored = self.settings.value("data_acquisition/listing_default_dir", "", type=str)
        if stored:
            self.listing_default_dir_edit.setText(stored)

    def _browse_listing_default_dir(self) -> None:
        start_dir = self.listing_default_dir_edit.text().strip() or str(Path.home())
        dir_path = QFileDialog.getExistingDirectory(
            self,
            "出品詳細レポートのデフォルトフォルダを選択",
            start_dir,
        )
        if dir_path:
            self.settings.setValue("data_acquisition/listing_default_dir", dir_path)
            self.listing_default_dir_edit.setText(dir_path)
            self._append_log(f"デフォルトフォルダ設定: {dir_path}")

    # --- ファイル選択 ---
    def _select_listing_file(self) -> None:
        base_dir = self.listing_default_dir_edit.text().strip() or str(Path.home())
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Amazon 在庫元帳レポートを選択",
            base_dir,
            "CSV/TSV/TXT ファイル (*.csv *.txt *.tsv);;すべてのファイル (*)",
        )
        if file_path:
            self.listing_file_edit.setText(file_path)
            self._append_log(f"[在庫元帳] ファイル選択: {file_path}")

    # --- トランザクション デフォルトフォルダ関連 ---
    def _load_transaction_default_dir(self) -> None:
        stored = self.settings.value("data_acquisition/transaction_default_dir", "", type=str)
        if stored:
            self.transaction_default_dir_edit.setText(stored)

    def _browse_transaction_default_dir(self) -> None:
        start_dir = self.transaction_default_dir_edit.text().strip() or str(Path.home())
        dir_path = QFileDialog.getExistingDirectory(
            self,
            "トランザクションレポートのデフォルトフォルダを選択",
            start_dir,
        )
        if dir_path:
            self.settings.setValue("data_acquisition/transaction_default_dir", dir_path)
            self.transaction_default_dir_edit.setText(dir_path)
            self._append_log(f"[トランザクション] デフォルトフォルダ設定: {dir_path}")

    # --- トランザクション ファイル選択 ---
    def _select_transaction_file(self) -> None:
        base_dir = self.transaction_default_dir_edit.text().strip() or str(Path.home())
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Amazon 月次トランザクションレポートを選択",
            base_dir,
            "CSV/TSV/TXT ファイル (*.csv *.txt *.tsv);;すべてのファイル (*)",
        )
        if file_path:
            self.transaction_file_edit.setText(file_path)
            self._append_log(f"[トランザクション] ファイル選択: {file_path}")

    # --- 実処理 ---
    def _run_listing_import(self) -> None:
        file_path = self.listing_file_edit.text().strip()
        if not file_path:
            QMessageBox.warning(self, "ファイル未選択", "在庫元帳レポートのファイルを選択してください。")
            return

        try:
            sku_to_date = self._parse_listing_report(file_path)
        except Exception as e:
            QMessageBox.critical(self, "解析エラー", f"在庫元帳レポートの解析に失敗しました。\n{e}")
            return

        if not sku_to_date:
            QMessageBox.information(self, "データなし", "SKU と出品日が取得できませんでした。")
            return

        updated_products = 0
        updated_purchases = 0

        for sku, listed_date in sku_to_date.items():
            try:
                # 商品DB: 存在するSKUのみ部分更新（存在しなければスキップ）
                product = self.product_db.get_by_sku(sku)
                if product:
                    current = (product.get("listed_date") or "").strip()
                    if not current or current != listed_date:
                        product_update = {"sku": sku, "listed_date": listed_date}
                        self.product_db.upsert(product_update)
                        updated_products += 1
                    else:
                        self._append_log(f"[商品DB] 変更なしのためスキップ SKU={sku}")
            except Exception:
                # 個別エラーはログだけにして続行
                self._append_log(f"[商品DB] 更新失敗 SKU={sku}")

            try:
                # 仕入DB: 存在するSKUのみ部分更新（存在しなければスキップ）
                purchase = self.purchase_db.get_by_sku(sku)
                if purchase:
                    current = (purchase.get("listed_date") or "").strip()
                    if not current or current != listed_date:
                        self.purchase_db.upsert({"sku": sku, "listed_date": listed_date})
                        updated_purchases += 1
                    else:
                        self._append_log(f"[仕入DB] 変更なしのためスキップ SKU={sku}")
            except Exception:
                self._append_log(f"[仕入DB] 更新失敗 SKU={sku}")

        self._append_log(
            f"更新完了: 商品DB {updated_products} 件, 仕入DB {updated_purchases} 件（ファイル: {file_path}）"
        )
        QMessageBox.information(
            self,
            "出品日反映完了",
            f"商品DB: {updated_products} 件\n仕入DB: {updated_purchases} 件\nに出品日を反映しました。",
        )

    # --- トランザクション取り込み実処理 ---
    def _run_transaction_import(self) -> None:
        file_path = self.transaction_file_edit.text().strip()
        if not file_path:
            QMessageBox.warning(self, "ファイル未選択", "トランザクションレポートのファイルを選択してください。")
            return

        try:
            sales_rows = self._parse_transaction_report(file_path)
        except Exception as e:
            QMessageBox.critical(self, "解析エラー", f"トランザクションレポートの解析に失敗しました。\n{e}")
            return

        if not sales_rows:
            QMessageBox.information(self, "データなし", "販売DBに取り込むレコードが見つかりませんでした。")
            return

        # 既存の販売データは一度クリアしてから再取り込み
        try:
            self.sales_db.delete_all()
            self._append_log("[トランザクション] 既存の販売データをクリアしました。")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"既存販売データのクリアに失敗しました:\n{e}")
            return

        inserted = 0
        for row in sales_rows:
            try:
                self.sales_db.insert(row)
                inserted += 1
            except Exception as e:  # 個別エラーはログだけにして続行
                self._append_log(f"[トランザクション] 挿入失敗 SKU={row.get('sku')} order_id={row.get('order_id')} error={e}")

        self._append_log(f"[トランザクション] 取り込み完了: {inserted} 件（ファイル: {file_path}）")
        QMessageBox.information(
            self,
            "トランザクション取り込み完了",
            f"販売DBに {inserted} 件のレコードを取り込みました。",
        )

    def _parse_listing_report(self, file_path: str) -> Dict[str, str]:
        """
        Amazon 在庫元帳レポート/出品詳細レポートから {SKU: 'YYYY-MM-DD'} の辞書を作成する。
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(str(path))

        # 日本のAmazonレポートは多くが cp932/shift_jis だが、
        # UTF-8(BOM付き含む) など他のエンコーディングの可能性もあるため複数パターンを試す
        last_error: Exception | None = None
        df = None
        for enc in ("cp932", "shift_jis", "utf-8-sig", "utf-8"):
            try:
                # 区切り文字は自動判定（CSV/TSV両対応）
                df = pd.read_csv(path, encoding=enc, sep=None, engine="python")
                self._append_log(f"読み込み成功: encoding={enc}")
                break
            except Exception as e:  # UnicodeDecodeError含む
                last_error = e
                continue

        if df is None:
            raise RuntimeError(f"出品詳細レポートの読み込みに失敗しました: {last_error}")

        # 列名の揺れ対策（全候補を見る場合はここを拡張）
        sku_col_candidates = ["出品者SKU", "出品者sku", "seller-sku", "SKU", "sku"]
        # 出品詳細レポート: 出品日
        # 在庫元帳レポート: スナップショット日付（先頭カラム）
        date_col_candidates = ["出品日", "listing-date", "listing_date", "スナップショット日付"]

        sku_col = next((c for c in sku_col_candidates if c in df.columns), None)
        date_col = next((c for c in date_col_candidates if c in df.columns), None)

        if not sku_col or not date_col:
            raise ValueError(f"必要な列が見つかりません。SKU列候補={sku_col_candidates}, 出品日列候補={date_col_candidates}")

        df = df[[sku_col, date_col]].dropna(subset=[sku_col, date_col])

        # 日付を正規化（"2025/12/21 00:16:29 JST" → "2025-12-21"）
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce").dt.date.astype("string")
        df = df.dropna(subset=[date_col])

        sku_to_date: Dict[str, str] = {}
        for _, row in df.iterrows():
            sku = str(row[sku_col]).strip()
            listed_date = str(row[date_col]).strip()
            if not sku or not listed_date:
                continue

            # 同一SKUが複数ある場合は一番古い日付を採用
            if sku in sku_to_date:
                if listed_date < sku_to_date[sku]:
                    sku_to_date[sku] = listed_date
            else:
                sku_to_date[sku] = listed_date

        self._append_log(f"解析結果: {len(sku_to_date)} SKU の出品日を取得")
        return sku_to_date

    def _parse_transaction_report(self, file_path: str):
        """
        Amazon 月次トランザクションレポートから販売DB用の行リストを作成する。
        """
        from io import StringIO

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(str(path))

        last_error: Exception | None = None
        df = None

        # エンコーディングを変えながらトライ
        for enc in ("cp932", "shift_jis", "utf-8-sig", "utf-8"):
            try:
                # まずテキストとして全行読み込む
                with open(path, "r", encoding=enc) as f:
                    lines = f.readlines()

                # 「日付/時間」と「SKU」を含む行をヘッダー行として検出
                header_idx = None
                for idx, line in enumerate(lines):
                    if "日付/時間" in line and "SKU" in line:
                        header_idx = idx
                        break

                # このエンコーディングではヘッダーが見つからない → 次のencへ
                if header_idx is None:
                    continue

                # ヘッダー行以降だけを切り出して read_csv に渡す
                content = "".join(lines[header_idx:])
                df = pd.read_csv(
                    StringIO(content),
                    sep=None,
                    engine="python",
                    dtype=str,
                    on_bad_lines="warn",
                )
                self._append_log(
                    f"[トランザクション] 読み込み成功: encoding={enc}, header_row={header_idx + 1}"
                )
                break
            except Exception as e:
                last_error = e
                continue

        if df is None:
            raise RuntimeError(f"トランザクションレポートの読み込みに失敗しました: {last_error}")

        # 必要な列名
        required_cols = {
            "日付/時間": None,
            "トランザクションの種類": None,
            "注文番号": None,
            "SKU": None,
            "数量": None,
            "説明": None,
            "商品売上": None,
            "配送料": None,
            "ギフト包装手数料": None,
            "手数料": None,
            "FBA 手数料": None,
            "トランザクションに関するその他の手数料": None,
            "その他": None,
        }
        missing = [c for c in required_cols.keys() if c not in df.columns]
        if missing:
            raise ValueError(f"必要な列が見つかりません: {missing}")

        # 注文行のみ対象
        df = df[df["トランザクションの種類"] == "注文"].copy()
        if df.empty:
            return []

        # 日付を sale_date（YYYY-MM-DD） に正規化
        df["sale_date"] = pd.to_datetime(df["日付/時間"], errors="coerce").dt.date.astype("string")
        df = df.dropna(subset=["sale_date", "SKU"])

        sales_rows = []
        for _, row in df.iterrows():
            try:
                sku = str(row["SKU"]).strip()
                if not sku:
                    continue

                qty = int(str(row["数量"]).replace(",", "")) if pd.notna(row["数量"]) else 1
                if qty <= 0:
                    qty = 1

                title = str(row["説明"]).strip() if pd.notna(row["説明"]) else ""

                sale_price = int(str(row["商品売上"]).replace(",", "")) if pd.notna(row["商品売上"]) else 0
                shipping_fee = int(str(row["配送料"]).replace(",", "")) if pd.notna(row["配送料"]) else 0
                gift_wrap_fee = int(str(row["ギフト包装手数料"]).replace(",", "")) if pd.notna(row["ギフト包装手数料"]) else 0

                fee = int(str(row["手数料"]).replace(",", "")) if pd.notna(row["手数料"]) else 0
                fba_fee = int(str(row["FBA 手数料"]).replace(",", "")) if pd.notna(row["FBA 手数料"]) else 0
                other_fee1 = int(str(row["トランザクションに関するその他の手数料"]).replace(",", "")) if pd.notna(row["トランザクションに関するその他の手数料"]) else 0
                other_fee2 = int(str(row["その他"]).replace(",", "")) if pd.notna(row["その他"]) else 0

                # レポートでは手数料はマイナスで出てくるので、絶対値にして「費用」として保存
                platform_fee = abs(fee)
                fba_fee_val = abs(fba_fee)
                other_fees = abs(other_fee1) + abs(other_fee2)

                sale_dict = {
                    "purchase_id": None,
                    "inventory_status_id": None,
                    "sku": sku,
                    "sale_date": str(row["sale_date"]),
                    "sales_method": "FBA",
                    "platform": "Amazon",
                    "sale_price": sale_price,
                    "quantity": qty,
                    "title": title,
                    "platform_fee": platform_fee,
                    "shipping_fee": shipping_fee,
                    "fba_fee": fba_fee_val,
                    "storage_fee": 0,
                    "other_fees": other_fees,
                    "order_id": str(row["注文番号"]).strip() if pd.notna(row["注文番号"]) else None,
                    "buyer_name": None,
                    "transaction_method": str(row["トランザクションの種類"]).strip(),
                }
            except Exception as e:
                self._append_log(f"[トランザクション] 行の解析失敗: {e}")
                continue

            sales_rows.append(sale_dict)

        self._append_log(f"[トランザクション] 解析結果: {len(sales_rows)} 行の販売データを取得")
        return sales_rows

    def _append_log(self, message: str) -> None:
        self.log_edit.append(message)


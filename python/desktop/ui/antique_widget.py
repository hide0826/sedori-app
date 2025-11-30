#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
古物台帳ウィジェット

古物台帳の生成・表示・エクスポート機能
- 日付範囲選択
- フィルタ機能
- テーブル表示
- CSV/Excel出力
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QMessageBox, QDateEdit, QSpinBox, QCheckBox,
    QFileDialog, QProgressBar, QTextEdit, QTabWidget
)
from PySide6.QtCore import Qt, QDate, QThread, Signal, QSettings
from PySide6.QtGui import QFont, QColor
from typing import Optional, List, Dict, Any
import re
import pandas as pd
from pathlib import Path
import datetime


class AntiqueWorker(QThread):
    """古物台帳生成のワーカースレッド"""
    progress_updated = Signal(int)
    result_ready = Signal(dict)
    error_occurred = Signal(str)
    
    def __init__(self, start_date, end_date, api_client):
        super().__init__()
        self.start_date = start_date
        self.end_date = end_date
        self.api_client = api_client
        
    def run(self):
        """古物台帳生成処理の実行"""
        try:
            # 進捗更新
            self.progress_updated.emit(10)
            
            # API接続確認
            if not self.api_client.test_connection():
                raise Exception("FastAPIサーバーに接続できません。サーバーが起動しているか確認してください。")
            
            self.progress_updated.emit(30)
            
            # 古物台帳生成API呼び出し
            result = self.api_client.antique_register_generate(self.start_date, self.end_date)
            
            self.progress_updated.emit(100)
            
            # 結果を返す
            self.result_ready.emit(result)
            
        except Exception as e:
            self.error_occurred.emit(str(e))


class AntiqueWidget(QWidget):
    """古物台帳ウィジェット（サブタブ: 入力・生成 / 閲覧・出力）"""

    def __init__(self, api_client, inventory_widget=None):
        super().__init__()
        self.api_client = api_client
        # 仕入管理ウィジェット（取込元）への参照
        self.inventory_widget = inventory_widget
        self.antique_data = None
        # 13品目（区分）リスト（UI/辞書/編集ですべて共通利用）
        # 番号を削除した表示名を使用
        self.CATEGORY_CHOICES = [
            "美術品類","衣類","時計・宝飾品類","自動車","自動二輪車及び原動機付自転車",
            "自転車類","写真機類","事務機器類","機械工具類","道具類",
            "皮革・ゴム製品類","書籍","金券類"
        ]
        # 統一スキーマ（列キー→日本語見出し）
        # 区分13と品目を統合: 表示上は「品目」に区分13を表示
        self.COMMON_COLUMNS = [
            ("entry_date", "取引日"),
            ("kobutsu_kind", "品目"),  # 区分13を「品目」として表示
            ("hinmei", "品名"),
            ("transaction_method", "取引方法"),  # 表示専用（買受固定）
            ("qty", "数量"),
            ("unit_price", "単価"),
            ("amount", "金額"),
            ("identifier", "識別情報"),
            ("counterparty_type", "相手区分"),
            ("notes", "備考"),
        ]
        self.STORE_COLUMNS = [
            ("counterparty_name", "仕入先名"),
            ("counterparty_branch", "支店"),
            ("counterparty_address", "店舗住所"),
            ("contact", "連絡先"),
            ("receipt_no", "レシート番号"),
        ]
        self.FLEA_COLUMNS = [
            ("platform", "プラットフォーム"),
            ("platform_order_id", "取引ID"),
            ("platform_user", "ユーザー名"),
            ("listing_url", "出品URL"),
            ("tracking_no", "伝票番号"),
            ("ship_to_prefecture", "受取都道府県"),
        ]
        self.PERSON_COLUMNS = [
            ("person_name", "氏名"),
            ("person_address", "個人住所"),
            ("person_dob", "生年月日"),
            ("id_type", "本人確認種別"),
            ("id_number", "番号"),
            ("id_checked_on", "確認日"),
            ("id_checked_by", "確認者"),
            ("id_proof_ref", "証憑参照"),
        ]
        self.ALL_COLUMNS = self.COMMON_COLUMNS + self.STORE_COLUMNS + self.FLEA_COLUMNS + self.PERSON_COLUMNS

        # サブタブ
        self.tabs = QTabWidget()
        self.tab_input = QWidget()
        self.tab_view = QWidget()
        self.tab_dict = QWidget()
        self.tabs.addTab(self.tab_input, "入力・生成")
        self.tabs.addTab(self.tab_view, "閲覧・出力")
        self.tabs.addTab(self.tab_dict, "ユーザー辞書")

        root = QVBoxLayout(self)
        root.addWidget(self.tabs)

        # それぞれのタブを構築（列スキーマ定義後に呼ぶ）
        self._setup_tab_input()
        self._setup_tab_view()
        self._setup_tab_dict()
        
    # ===== 入力・生成タブ =====
    def _setup_tab_input(self):
        lay = QVBoxLayout(self.tab_input)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(10)

        # 相手区分（高さを拡張し操作ボタンを配置）
        grp_counter = QGroupBox("相手区分")
        h = QHBoxLayout(grp_counter)
        h.setContentsMargins(10, 10, 10, 10)
        h.setSpacing(10)
        self.cmb_counterparty = QComboBox()
        self.cmb_counterparty.addItems(["店舗", "フリマ", "個人"])
        h.addWidget(QLabel("区分:"))
        h.addWidget(self.cmb_counterparty)

        # 店舗用：仕入リスト取込ボタン
        self.btn_import_store = QPushButton("仕入リスト取込")
        self.btn_import_store.setToolTip("CSVから店舗の仕入リストを取り込みます")
        h.addWidget(self.btn_import_store)

        # テンプレート表示の折りたたみトグル
        self.btn_toggle_template = QPushButton("テンプレートを展開")
        self.btn_toggle_template.setCheckable(True)
        self.btn_toggle_template.setChecked(True)  # デフォルトで畳む
        h.addWidget(self.btn_toggle_template)

        h.addStretch()
        # 高さを広げる
        grp_counter.setMaximumHeight(72)
        lay.addWidget(grp_counter)

        # 入力フォーム（最小）
        form = QGroupBox("テンプレート（最低限）")
        g = QGridLayout(form)
        g.setContentsMargins(10, 10, 10, 10)
        g.setSpacing(8)
        # テンプレート領域を大きく確保
        from PySide6.QtWidgets import QSizePolicy
        sp = form.sizePolicy()
        sp.setHorizontalPolicy(QSizePolicy.Expanding)
        sp.setVerticalPolicy(QSizePolicy.Expanding)
        form.setSizePolicy(sp)
        form.setMinimumHeight(360)
        row = 0
        self.ed_entry_date = QDateEdit(); self.ed_entry_date.setCalendarPopup(True); self.ed_entry_date.setDate(QDate.currentDate())
        g.addWidget(QLabel("取引日"), row, 0); g.addWidget(self.ed_entry_date, row, 1); row += 1
        # 区分13と品目を統合: 品目コンボ（区分13を選択）
        self.cmb_kobutsu = QComboBox(); self.cmb_kobutsu.addItems(self.CATEGORY_CHOICES)
        # デフォルトで「道具類」を選択（インデックス9）
        idx_tool = self.CATEGORY_CHOICES.index("道具類") if "道具類" in self.CATEGORY_CHOICES else 9
        self.cmb_kobutsu.setCurrentIndex(idx_tool)
        g.addWidget(QLabel("品目(区分13)"), row, 0); g.addWidget(self.cmb_kobutsu, row, 1); row += 1
        self.ed_hinmei = QLineEdit(); g.addWidget(QLabel("品名"), row, 0); g.addWidget(self.ed_hinmei, row, 1); row += 1
        # 品名右に取引方法（買受固定）
        self.transaction_method = QLineEdit(); self.transaction_method.setText("買受"); self.transaction_method.setReadOnly(True)
        g.addWidget(QLabel("取引方法"), row-1, 2); g.addWidget(self.transaction_method, row-1, 3)
        self.sp_qty = QSpinBox(); self.sp_qty.setRange(1, 9999); self.sp_qty.setValue(1)
        g.addWidget(QLabel("数量"), row, 0); g.addWidget(self.sp_qty, row, 1); row += 1
        self.sp_unit = QSpinBox(); self.sp_unit.setRange(0, 10_000_000)
        g.addWidget(QLabel("単価"), row, 0); g.addWidget(self.sp_unit, row, 1); row += 1
        self.ed_identifier = QLineEdit(); g.addWidget(QLabel("識別情報(JAN/ISBN/ASIN/Serial)"), row, 0); g.addWidget(self.ed_identifier, row, 1); row += 1

        # 相手区分別フォーム
        # 店舗
        self.grp_store = QGroupBox("店舗用")
        gs = QGridLayout(self.grp_store); sr=0
        self.store_name = QLineEdit(); gs.addWidget(QLabel("仕入先名"), sr,0); gs.addWidget(self.store_name, sr,1); sr+=1
        self.store_branch = QLineEdit(); gs.addWidget(QLabel("支店"), sr,0); gs.addWidget(self.store_branch, sr,1); sr+=1
        self.store_address = QLineEdit(); gs.addWidget(QLabel("住所"), sr,0); gs.addWidget(self.store_address, sr,1); sr+=1
        self.store_contact = QLineEdit(); gs.addWidget(QLabel("連絡先"), sr,0); gs.addWidget(self.store_contact, sr,1); sr+=1
        self.store_receipt = QLineEdit(); gs.addWidget(QLabel("レシート番号"), sr,0); gs.addWidget(self.store_receipt, sr,1); sr+=1
        g.addWidget(self.grp_store, row, 0, 1, 2); row += 1

        # フリマ
        self.grp_flea = QGroupBox("フリマ用")
        gf = QGridLayout(self.grp_flea); fr=0
        self.flea_platform = QLineEdit(); gf.addWidget(QLabel("プラットフォーム"), fr,0); gf.addWidget(self.flea_platform, fr,1); fr+=1
        self.flea_order_id = QLineEdit(); gf.addWidget(QLabel("取引ID"), fr,0); gf.addWidget(self.flea_order_id, fr,1); fr+=1
        self.flea_user = QLineEdit(); gf.addWidget(QLabel("ユーザー名"), fr,0); gf.addWidget(self.flea_user, fr,1); fr+=1
        self.flea_url = QLineEdit(); gf.addWidget(QLabel("出品URL"), fr,0); gf.addWidget(self.flea_url, fr,1); fr+=1
        self.flea_tracking = QLineEdit(); gf.addWidget(QLabel("伝票番号"), fr,0); gf.addWidget(self.flea_tracking, fr,1); fr+=1
        self.flea_pref = QLineEdit(); gf.addWidget(QLabel("受取都道府県"), fr,0); gf.addWidget(self.flea_pref, fr,1); fr+=1
        g.addWidget(self.grp_flea, row, 0, 1, 2); row += 1

        # 個人
        self.grp_person = QGroupBox("個人用")
        gp = QGridLayout(self.grp_person); pr=0
        self.person_name = QLineEdit(); gp.addWidget(QLabel("氏名"), pr,0); gp.addWidget(self.person_name, pr,1); pr+=1
        self.person_address = QLineEdit(); gp.addWidget(QLabel("住所"), pr,0); gp.addWidget(self.person_address, pr,1); pr+=1
        self.person_dob = QLineEdit(); gp.addWidget(QLabel("生年月日"), pr,0); gp.addWidget(self.person_dob, pr,1); pr+=1
        self.id_type = QLineEdit(); gp.addWidget(QLabel("本人確認種別"), pr,0); gp.addWidget(self.id_type, pr,1); pr+=1
        self.id_number = QLineEdit(); gp.addWidget(QLabel("番号"), pr,0); gp.addWidget(self.id_number, pr,1); pr+=1
        self.id_checked_on = QLineEdit(); gp.addWidget(QLabel("確認日"), pr,0); gp.addWidget(self.id_checked_on, pr,1); pr+=1
        self.id_checked_by = QLineEdit(); gp.addWidget(QLabel("確認者"), pr,0); gp.addWidget(self.id_checked_by, pr,1); pr+=1
        self.id_proof_ref = QLineEdit(); gp.addWidget(QLabel("証憑参照"), pr,0); gp.addWidget(self.id_proof_ref, pr,1); pr+=1
        g.addWidget(self.grp_person, row, 0, 1, 2); row += 1

        lay.addWidget(form)
        self._template_form = form  # 折りたたみ対象
        # 初期状態は非表示（畳み）
        self._template_form.setVisible(False)

        # 店舗向け：下部リスト表示（店舗用項目）
        from PySide6.QtWidgets import QSizePolicy
        self.grp_store_list = QGroupBox("店舗リスト（取込プレビュー）")
        vl_store_list = QVBoxLayout(self.grp_store_list)
        
        # 削除ボタンエリア
        btn_store_list_layout = QHBoxLayout()
        self.btn_delete_selected_store = QPushButton("選択行削除")
        self.btn_delete_selected_store.setEnabled(False)
        self.btn_delete_selected_store.clicked.connect(self._delete_selected_store_rows)
        btn_store_list_layout.addWidget(self.btn_delete_selected_store)
        
        self.btn_delete_all_store = QPushButton("リスト全削除")
        self.btn_delete_all_store.setEnabled(False)
        self.btn_delete_all_store.clicked.connect(self._delete_all_store_rows)
        btn_store_list_layout.addWidget(self.btn_delete_all_store)
        
        btn_store_list_layout.addStretch()
        vl_store_list.addLayout(btn_store_list_layout)
        
        self.table_store_list = QTableWidget()
        self.table_store_list.setAlternatingRowColors(True)
        self.table_store_list.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_store_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # 選択変更時に削除ボタンの有効/無効を切り替え
        self.table_store_list.itemSelectionChanged.connect(self._on_store_list_selection_changed)
        # プレビュー列は『共通列+店舗列』（閲覧・出力タブと同じ並び）
        self.preview_columns = self.COMMON_COLUMNS + self.STORE_COLUMNS
        self.preview_headers = [label for _, label in self.preview_columns]
        self.preview_keys = [key for key, _ in self.preview_columns]
        self.table_store_list.setColumnCount(len(self.preview_headers))
        self.table_store_list.setHorizontalHeaderLabels(self.preview_headers)
        vl_store_list.addWidget(self.table_store_list)
        lay.addWidget(self.grp_store_list)

        # アクション
        actions = QHBoxLayout()
        self.btn_draft = QPushButton("ドラフト保存")
        self.btn_commit = QPushButton("確定（コミット）")
        self.btn_commit_bulk = QPushButton("取込プレビュー一括登録")
        # ボタンは常に有効（取込プレビューにデータがあるかは処理内でチェック）
        self.btn_commit_bulk.setEnabled(True)
        actions.addWidget(self.btn_draft)
        actions.addWidget(self.btn_commit)
        actions.addWidget(self.btn_commit_bulk)
        actions.addStretch()
        lay.addLayout(actions)

        # イベント
        self.btn_commit.clicked.connect(self._commit_single_row)
        # ドラフト保存も同じ保存処理を暫定適用（将来分岐可能）
        self.btn_draft.clicked.connect(self._commit_single_row)
        self.cmb_counterparty.currentTextChanged.connect(self._on_counterparty_changed)
        self.btn_import_store.clicked.connect(self._on_import_store_clicked)
        self.btn_toggle_template.toggled.connect(self._on_toggle_template)
        # 品名変更時に簡易推定（ユーザー辞書）
        self.ed_hinmei.textChanged.connect(self._predict_category_from_name)
        self.btn_commit_bulk.clicked.connect(self._commit_imported_store_rows)
        self._on_counterparty_changed(self.cmb_counterparty.currentText())

        # 取込データ保持
        self._imported_store_rows = []
        self._imported_route_info = None  # ルート情報（仕入管理タブから転送された場合）

    def _commit_single_row(self):
        """フォーム1行をバリデーションして ledger_entries に保存"""
        from desktop.database.ledger_db import LedgerDatabase
        # 必須チェック（最低限）
        missing = []
        # 品目はコンボボックス選択
        if not self.cmb_kobutsu.currentText().strip(): missing.append("品目")
        if not self.ed_hinmei.text().strip(): missing.append("品名")
        if not self.ed_identifier.text().strip(): missing.append("識別情報")
        cp = self.cmb_counterparty.currentText()
        if cp == '店舗':
            if not self.store_name.text().strip(): missing.append("仕入先名")
            # レシート番号は任意（未実装のため空でも可）
        elif cp == 'フリマ':
            if not self.flea_user.text().strip(): missing.append("ユーザー名")
            if not self.flea_order_id.text().strip(): missing.append("取引ID")
        elif cp == '個人':
            if not self.person_name.text().strip(): missing.append("氏名")
            if not self.id_number.text().strip(): missing.append("本人確認番号")
        if missing:
            QMessageBox.warning(self, "必須未入力", f"次を入力してください: {', '.join(missing)}")
            return

        qty = int(self.sp_qty.value()); unit = int(self.sp_unit.value()); amount = qty * unit
        row = {
            'entry_date': self.ed_entry_date.date().toString('yyyy-MM-dd'),
            'counterparty_type': cp,
            'counterparty_name': (self.store_name.text().strip() if cp == '店舗' else (self.person_name.text().strip() if cp == '個人' else None)),
            'counterparty_branch': self.store_name.text().strip() if cp == '店舗' else None,
            'counterparty_address': self.store_address.text().strip() if cp == '店舗' else None,
            'contact': self.store_contact.text().strip() if cp == '店舗' else None,
            'receipt_no': self.store_receipt.text().strip() if cp == '店舗' else None,
            'platform': 'フリマ' if cp == 'フリマ' else None,
            'platform_order_id': self.flea_order_id.text().strip() if cp == 'フリマ' else None,
            'platform_user': self.flea_user.text().strip() if cp == 'フリマ' else None,
            'person_name': self.person_name.text().strip() if cp == '個人' else None,
            'person_address': None,
            'id_type': 'ID',
            'id_number': self.id_number.text().strip() if cp == '個人' else None,
            'id_checked_on': None,
            'id_checked_by': None,
            'id_proof_ref': None,
            # 統合: 区分13=品目
            'kobutsu_kind': self.cmb_kobutsu.currentText(),
            'hinmoku': self.cmb_kobutsu.currentText(),
            'hinmei': self.ed_hinmei.text().strip(),
            'qty': qty,
            'unit_price': unit,
            'amount': amount,
            'identifier': self.ed_identifier.text().strip(),
            'transaction_method': '買受' if cp == '店舗' else (self.transaction_method.text().strip() if hasattr(self, 'transaction_method') else None),
            'notes': None,
            'correction_of': None
        }
        db = LedgerDatabase()
        db.insert_ledger_rows([row])
        try:
            self.reload_ledger_rows()
        except Exception:
            pass
        QMessageBox.information(self, "保存", "台帳に保存しました。『閲覧・出力』で確認できます。")

    def _on_counterparty_changed(self, text: str) -> None:
        """相手区分の切替に応じて、該当フォームのみを表示する。"""
        try:
            if hasattr(self, 'grp_store'):
                self.grp_store.setVisible(text == '店舗')
            if hasattr(self, 'grp_flea'):
                self.grp_flea.setVisible(text == 'フリマ')
            if hasattr(self, 'grp_person'):
                self.grp_person.setVisible(text == '個人')
            if hasattr(self, 'btn_import_store'):
                self.btn_import_store.setVisible(text == '店舗')
            if hasattr(self, 'grp_store_list'):
                self.grp_store_list.setVisible(text == '店舗')
        except Exception as e:
            print(f"counterparty toggle error: {e}")

    def _on_toggle_template(self, checked: bool) -> None:
        try:
            if hasattr(self, '_template_form'):
                self._template_form.setVisible(not checked)
            self.btn_toggle_template.setText("テンプレートを展開" if checked else "テンプレートを畳む")
        except Exception:
            pass

    # ===== ユーザー辞書による品目（区分13）推定 =====
    def _normalize_category_name(self, cat_name: str) -> str:
        """品目名から番号を削除して正規化（既存データとの互換性のため）"""
        if not cat_name:
            return ""
        # 番号（①②③...⑬）を削除
        import re
        normalized = re.sub(r'^[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬]\s*', '', cat_name)
        # 「電機機械類（道具類）」などは「道具類」にマッピング
        if "道具類" in normalized:
            return "道具類"
        return normalized.strip()
    
    def _normalize_date(self, date_str: str) -> str:
        """日付文字列から時刻部分を削除して yyyy-MM-dd 形式に正規化"""
        if not date_str:
            return ""
        import re
        from datetime import datetime
        # 文字列に変換
        date_str = str(date_str).strip()
        # 時刻部分を削除（スペース以降や時刻パターンを削除）
        # 例: "2025/11/2 10:42" -> "2025/11/2", "2025-11-02 10:42:00" -> "2025-11-02"
        date_str = re.sub(r'\s+\d{1,2}:\d{2}(:\d{2})?.*$', '', date_str)
        # 各種日付形式を yyyy-MM-dd に統一
        try:
            # yyyy/MM/dd 形式を試す
            if '/' in date_str:
                dt = datetime.strptime(date_str.split()[0], '%Y/%m/%d')
            # yyyy-MM-dd 形式を試す
            elif '-' in date_str:
                dt = datetime.strptime(date_str.split()[0], '%Y-%m-%d')
            else:
                # その他の形式はそのまま返す（エラー回避）
                return date_str.split()[0] if ' ' in date_str else date_str
            return dt.strftime('%Y-%m-%d')
        except (ValueError, AttributeError):
            # パースできない場合は空白以降を削除して返す
            return date_str.split()[0] if ' ' in date_str else date_str
    
    def _load_user_dictionary(self) -> dict:
        try:
            s = QSettings("HIRIO", "SedoriDesktopApp")
            data = s.value("ledger/user_dictionary", None)
            if isinstance(data, dict):
                return data
            # 既定の簡易辞書
            return {
                "本": "書籍",
                "DVD": "写真機類",
                "BD": "写真機類",
                "ゲーム": "事務機器類",
                "腕時計": "時計・宝飾品類",
                "カメラ": "道具類",
                "掃除機": "道具類",
                "Wi-Fi": "道具類",
                "ルーター": "道具類",
                "ジャケット": "衣類",
            }
        except Exception:
            return {}

    def _learn_category_edit(self, product_name: str, category: str, identifier: Optional[str] = None) -> None:
        """
        品目編集を学習する（非同期処理、エラーは無視）
        """
        try:
            from desktop.database.ledger_db import LedgerDatabase
            db = LedgerDatabase()
            result = db.learn_category_from_edit(product_name, category, identifier)
            # 学習結果はログに出力（デバッグ用）
            if result.get('keywords_added', 0) > 0 or result.get('id_mapped', 0) > 0:
                print(f"学習完了: キーワード{result.get('keywords_added', 0)}件, IDマッピング{result.get('id_mapped', 0)}件")
        except Exception as e:
            print(f"学習処理エラー: {e}")

    def _predict_category_from_name(self, name: str) -> None:
        """
        商品名から品目を推定してプルダウンに反映（学習データを優先）
        """
        try:
            name = name or ""
            cat = None
            
            # 1. 学習済みキーワード辞書から推定
            try:
                from desktop.database.ledger_db import LedgerDatabase
                db = LedgerDatabase()
                result = db.match_category_by_keywords(name)
                if result:
                    cat = result[0]  # 品目名を取得
            except Exception:
                pass
            
            # 2. ユーザー辞書（既存の簡易辞書）から推定
            if not cat:
                user_dict = self._load_user_dictionary()
                for key, cat_name in user_dict.items():
                    if key and key.lower() in name.lower():
                        cat = cat_name
                        break
            
            # 3. プルダウンに反映
            if cat:
                normalized_cat = self._normalize_category_name(cat)
                idx = self.cmb_kobutsu.findText(normalized_cat)
                if idx >= 0:
                    self.cmb_kobutsu.setCurrentIndex(idx)
        except Exception:
            pass

    # ===== ユーザー辞書タブ =====
    def _setup_tab_dict(self):
        from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem
        lay = QVBoxLayout(self.tab_dict)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(10)
        
        # 説明ラベル
        info_label = QLabel("各品目に関連するキーワードをカンマ区切りで入力してください")
        info_label.setStyleSheet("color: #888; font-size: 11px;")
        lay.addWidget(info_label)
        
        # テーブル: 13品目を固定で縦に展開
        self.dict_table = QTableWidget()
        self.dict_table.setColumnCount(2)
        self.dict_table.setHorizontalHeaderLabels(["品目", "キーワード（カンマ区切り）"])
        self.dict_table.setRowCount(len(self.CATEGORY_CHOICES))
        self.dict_table.verticalHeader().setVisible(False)
        
        # 各品目を行に配置
        for i, category in enumerate(self.CATEGORY_CHOICES):
            # 左列: 品目名（読み取り専用ラベル）
            item = QTableWidgetItem(category)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)  # 読み取り専用
            item.setBackground(QColor(240, 240, 240))  # 背景色を薄いグレーに
            self.dict_table.setItem(i, 0, item)
            
            # 右列: キーワード入力欄（QLineEdit）
            keyword_input = QLineEdit()
            keyword_input.setPlaceholderText("例: キーワード1,キーワード2,キーワード3")
            self.dict_table.setCellWidget(i, 1, keyword_input)
        
        # 列幅調整
        self.dict_table.setColumnWidth(0, 200)  # 品目列は固定幅
        self.dict_table.setColumnWidth(1, 400)  # キーワード列は広めに
        header = self.dict_table.horizontalHeader()
        header.setStretchLastSection(True)  # 最後の列を伸縮可能に
        
        lay.addWidget(self.dict_table)
        
        # ボタン（保存のみ）
        btns = QHBoxLayout()
        btns.addStretch()
        self.btn_dict_save = QPushButton("保存")
        self.btn_dict_save.clicked.connect(self._dict_save)
        btns.addWidget(self.btn_dict_save)
        lay.addLayout(btns)
        
        # データ読み込み
        self._dict_load()

    def _dict_load(self):
        """既存のユーザー辞書を読み込んで新しい形式に変換して表示"""
        try:
            # 既存の {キーワード: 品目} 形式を読み込み
            old_dict = self._load_user_dictionary()
            
            # 新しい形式 {品目: [キーワード1, キーワード2, ...]} に変換
            category_keywords = {}
            for keyword, category in old_dict.items():
                normalized_cat = self._normalize_category_name(category)
                if normalized_cat not in category_keywords:
                    category_keywords[normalized_cat] = []
                category_keywords[normalized_cat].append(keyword)
            
            # テーブルに反映
            for i, category in enumerate(self.CATEGORY_CHOICES):
                keywords = category_keywords.get(category, [])
                keyword_text = ",".join(keywords) if keywords else ""
                keyword_input = self.dict_table.cellWidget(i, 1)
                if keyword_input:
                    keyword_input.setText(keyword_text)
        except Exception as e:
            print(f"辞書読み込みエラー: {e}")

    def _dict_save(self):
        """新しい形式で保存（{品目: "キーワード1,キーワード2,..."} 形式）"""
        try:
            # 新しい形式でデータを収集
            category_keywords_dict = {}
            for i, category in enumerate(self.CATEGORY_CHOICES):
                keyword_input = self.dict_table.cellWidget(i, 1)
                if keyword_input:
                    keyword_text = keyword_input.text().strip()
                    if keyword_text:
                        # カンマ区切りのキーワードをリストに変換
                        keywords = [k.strip() for k in keyword_text.split(",") if k.strip()]
                        if keywords:
                            category_keywords_dict[category] = ",".join(keywords)
            
            # 既存の {キーワード: 品目} 形式に変換して保存（互換性のため）
            # ただし、学習機能が優先されるので、この辞書は補助的な役割
            legacy_dict = {}
            for category, keywords_str in category_keywords_dict.items():
                keywords = [k.strip() for k in keywords_str.split(",") if k.strip()]
                for keyword in keywords:
                    legacy_dict[keyword] = category
            
            s = QSettings("HIRIO", "SedoriDesktopApp")
            # 新しい形式も保存（将来の拡張用）
            s.setValue("ledger/user_dictionary_v2", category_keywords_dict)
            # 既存形式も保存（互換性のため）
            s.setValue("ledger/user_dictionary", legacy_dict)
            
            QMessageBox.information(self, "保存", "ユーザー辞書を保存しました")
        except Exception as e:
            QMessageBox.warning(self, "保存エラー", str(e))

    def _on_import_store_clicked(self) -> None:
        """店舗用：仕入管理の『取り込んだデータ一覧』から取得し、下部リストに表示"""
        try:
            import pandas as pd
            # 仕入管理ウィジェット参照確認
            if not getattr(self, 'inventory_widget', None):
                QMessageBox.information(self, "情報", "仕入管理でデータを展開してください（ウィジェット参照なし）")
                return
            # テーブルの現在データを取得
            df = self.inventory_widget.get_table_data()
            if df is None or len(df) == 0:
                QMessageBox.information(self, "情報", "仕入管理の『取り込んだデータ一覧』にデータがありません。先に仕入管理でCSV取込または保存データを展開してください。")
                return

            # 列の取得（inventory_widgetの列名は日本語で統一済み）
            def pick_series(name: str) -> pd.Series:
                return df[name] if name in df.columns else pd.Series([""] * len(df))

            date_s = pick_series("仕入れ日")
            title_s = pick_series("商品名")
            qty_s = pick_series("仕入れ個数")
            unit_s = pick_series("仕入れ価格")
            asin_s = pick_series("ASIN")
            jan_s = pick_series("JAN")
            sku_s = pick_series("SKU")
            notes_s = pick_series("コメント")
            name_s = pick_series("仕入先")

            user_dict = self._load_user_dictionary()
            # 法人マスタを一括取得（チェーン名→法人名）
            company_rows = []
            try:
                from desktop.database.store_db import StoreDatabase
                _sdb_for_company = StoreDatabase()
                company_rows = _sdb_for_company.list_companies()
            except Exception:
                company_rows = []
            rows = []
            for i in range(len(df)):
                # 数値正規化
                def to_int(v):
                    try:
                        s = str(v).replace(',', '').strip()
                        return int(float(s)) if s not in ('', 'nan') else 0
                    except Exception:
                        return 0
                qty_v = to_int(qty_s.iloc[i])
                unit_v = to_int(unit_s.iloc[i])
                amount_v = qty_v * unit_v
                identifier_v = str(jan_s.iloc[i] or '') or str(asin_s.iloc[i] or '')
                # 品名から区分推定（学習データを優先）
                cat = ""
                title_val = str(title_s.iloc[i])
                
                # 1. 識別情報（JAN/ASIN）から直接マッチング（最高優先度）
                if identifier_v:
                    try:
                        from desktop.database.ledger_db import LedgerDatabase
                        db = LedgerDatabase()
                        matched = db.match_category_by_id(identifier_v)
                        if matched:
                            cat = matched
                    except Exception:
                        pass
                
                # 2. 学習済みキーワード辞書から推定
                if not cat:
                    try:
                        from desktop.database.ledger_db import LedgerDatabase
                        db = LedgerDatabase()
                        result = db.match_category_by_keywords(title_val)
                        if result:
                            cat = result[0]  # 品目名を取得
                    except Exception:
                        pass
                
                # 3. ユーザー辞書（既存の簡易辞書）から推定
                if not cat:
                    for key, cat_name in user_dict.items():
                        if key and key.lower() in (title_val or "").lower():
                            cat = cat_name
                            break
                
                # 4. デフォルト（マッチしない場合は空文字のまま、後で「道具類」が設定される）

                # 仕入先コード→店舗マスタ参照
                supplier_code = str(name_s.iloc[i] or '').strip()
                store_name = ""; address=""; phone=""; corp_name=""
                try:
                    if supplier_code:
                        from desktop.database.store_db import StoreDatabase
                        sdb = StoreDatabase()
                        st = sdb.get_store_by_supplier_code(supplier_code)
                        if st:
                            store_name = st.get('store_name','')
                            address = st.get('address','')
                            phone = st.get('phone','')
                            cf = st.get('custom_fields',{}) or {}
                            # 候補キーから法人/チェーン名を推測
                            for k in ['chain_name','chain','corporation','corp_name','法人名','チェーン名']:
                                if k in cf and cf.get(k):
                                    corp_name = cf.get(k); break
                
                    # 法人マスタでチェーン名キーワードマッチ（支店名→チェーン名→法人名）
                    if not corp_name:
                        branch_text = store_name or supplier_code
                        bt_norm = str(branch_text or '').replace('　',' ').strip()
                        def norm(s: str) -> str:
                            return str(s or '').replace('　',' ').strip()
                        best_match = None
                        for comp in company_rows:
                            chain = norm(comp.get('chain_name',''))
                            if not chain:
                                continue
                            # 完全一致/部分一致の両方を許容
                            if chain in bt_norm or bt_norm in chain:
                                best_match = comp
                                break
                            # チェーン名を区切りで分解して部分一致ワードを探す
                            for token in [t for t in re.split(r"[\s\-/・()（）]+", chain) if len(t) >= 2]:
                                if token and token in bt_norm:
                                    best_match = comp
                                    break
                            if best_match:
                                break
                        if best_match:
                            corp_name = best_match.get('company_name','')
                except Exception:
                    pass

                # 取引日の時刻部分を削除
                date_val = str(date_s.iloc[i]) if pd.notna(date_s.iloc[i]) else ""
                normalized_date = self._normalize_date(date_val) if date_val else ""
                
                rows.append({
                    # 共通列
                    "entry_date": normalized_date,
                    "kobutsu_kind": cat,
                    "hinmei": str(title_s.iloc[i]),
                    "transaction_method": "買受",
                    "qty": qty_v,
                    "unit_price": unit_v,
                    "amount": amount_v,
                    "identifier": identifier_v,
                    "counterparty_type": "店舗",
                    "notes": str(notes_s.iloc[i]),
                    # 店舗列（支店/住所/連絡先/レシート番号は不明のため空）
                    "counterparty_name": corp_name,  # 仕入先名（法人）
                    "counterparty_branch": store_name if store_name else supplier_code,  # 支店（店舗名）
                    "counterparty_address": address,
                    "contact": phone,
                    "receipt_no": "",
                })

            self._imported_store_rows = rows
            self._refresh_store_list_table()
            # ボタンは常に有効（処理内でデータチェック）
            QMessageBox.information(self, "取込完了", f"仕入管理から {len(rows)} 件を取り込みました。")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"取込でエラーが発生しました:\n{e}")
    
    def import_inventory_data(self, records: List[dict], route_info: Optional[dict] = None) -> None:
        """
        仕入管理タブからデータを受け取って古物台帳タブに表示する
        
        Args:
            records: 仕入データのリスト（辞書形式）
            route_info: ルート情報（オプション）
        """
        try:
            import pandas as pd
            
            if not records or len(records) == 0:
                QMessageBox.information(self, "情報", "転送するデータがありません。")
                return
            
            # ルート情報を内部メンバーに保持（後続処理で活用可能）
            self._imported_route_info = route_info
            
            # データフレームに変換（既存の処理と互換性を保つ）
            df = pd.DataFrame(records)
            
            # 列の取得（inventory_widgetの列名は日本語で統一済み）
            def pick_series(name: str) -> pd.Series:
                return df[name] if name in df.columns else pd.Series([""] * len(df))
            
            date_s = pick_series("仕入れ日")
            title_s = pick_series("商品名")
            qty_s = pick_series("仕入れ個数")
            unit_s = pick_series("仕入れ価格")
            asin_s = pick_series("ASIN")
            jan_s = pick_series("JAN")
            sku_s = pick_series("SKU")
            notes_s = pick_series("コメント")
            name_s = pick_series("仕入先")
            
            user_dict = self._load_user_dictionary()
            # 法人マスタを一括取得（チェーン名→法人名）
            company_rows = []
            try:
                from desktop.database.store_db import StoreDatabase
                _sdb_for_company = StoreDatabase()
                company_rows = _sdb_for_company.list_companies()
            except Exception:
                company_rows = []
            
            rows = []
            for i in range(len(df)):
                # 数値正規化
                def to_int(v):
                    try:
                        s = str(v).replace(',', '').strip()
                        return int(float(s)) if s not in ('', 'nan') else 0
                    except Exception:
                        return 0
                qty_v = to_int(qty_s.iloc[i])
                unit_v = to_int(unit_s.iloc[i])
                amount_v = qty_v * unit_v
                identifier_v = str(jan_s.iloc[i] or '') or str(asin_s.iloc[i] or '')
                
                # 品名から区分推定（学習データを優先）
                cat = ""
                title_val = str(title_s.iloc[i])
                
                # 1. 識別情報（JAN/ASIN）から直接マッチング（最高優先度）
                if identifier_v:
                    try:
                        from desktop.database.ledger_db import LedgerDatabase
                        db = LedgerDatabase()
                        matched = db.match_category_by_id(identifier_v)
                        if matched:
                            cat = matched
                    except Exception:
                        pass
                
                # 2. 学習済みキーワード辞書から推定
                if not cat:
                    try:
                        from desktop.database.ledger_db import LedgerDatabase
                        db = LedgerDatabase()
                        result = db.match_category_by_keywords(title_val)
                        if result:
                            cat = result[0]  # 品目名を取得
                    except Exception:
                        pass
                
                # 3. ユーザー辞書（既存の簡易辞書）から推定
                if not cat:
                    for key, cat_name in user_dict.items():
                        if key and key.lower() in (title_val or "").lower():
                            cat = cat_name
                            break
                
                # 仕入先コード→店舗マスタ参照
                supplier_code = str(name_s.iloc[i] or '').strip()
                store_name = ""; address=""; phone=""; corp_name=""
                try:
                    if supplier_code:
                        from desktop.database.store_db import StoreDatabase
                        sdb = StoreDatabase()
                        st = sdb.get_store_by_supplier_code(supplier_code)
                        if st:
                            store_name = st.get('store_name','')
                            address = st.get('address','')
                            phone = st.get('phone','')
                            cf = st.get('custom_fields',{}) or {}
                            # 候補キーから法人/チェーン名を推測
                            for k in ['chain_name','chain','corporation','corp_name','法人名','チェーン名']:
                                if k in cf and cf.get(k):
                                    corp_name = cf.get(k); break
                    
                    # 法人マスタでチェーン名キーワードマッチ（支店名→チェーン名→法人名）
                    if not corp_name:
                        branch_text = store_name or supplier_code
                        bt_norm = str(branch_text or '').replace('　',' ').strip()
                        def norm(s: str) -> str:
                            return str(s or '').replace('　',' ').strip()
                        best_match = None
                        for comp in company_rows:
                            chain = norm(comp.get('chain_name',''))
                            if not chain:
                                continue
                            # 完全一致/部分一致の両方を許容
                            if chain in bt_norm or bt_norm in chain:
                                best_match = comp
                                break
                            # チェーン名を区切りで分解して部分一致ワードを探す
                            for token in [t for t in re.split(r"[\s\-/・()（）]+", chain) if len(t) >= 2]:
                                if token and token in bt_norm:
                                    best_match = comp
                                    break
                            if best_match:
                                break
                        if best_match:
                            corp_name = best_match.get('company_name','')
                except Exception:
                    pass
                
                # 取引日の時刻部分を削除
                date_val = str(date_s.iloc[i]) if pd.notna(date_s.iloc[i]) else ""
                normalized_date = self._normalize_date(date_val) if date_val else ""
                
                rows.append({
                    # 共通列
                    "entry_date": normalized_date,
                    "kobutsu_kind": cat,
                    "hinmei": str(title_s.iloc[i]),
                    "transaction_method": "買受",
                    "qty": qty_v,
                    "unit_price": unit_v,
                    "amount": amount_v,
                    "identifier": identifier_v,
                    "counterparty_type": "店舗",
                    "notes": str(notes_s.iloc[i]),
                    # 店舗列（支店/住所/連絡先/レシート番号は不明のため空）
                    "counterparty_name": corp_name,  # 仕入先名（法人）
                    "counterparty_branch": store_name if store_name else supplier_code,  # 支店（店舗名）
                    "counterparty_address": address,
                    "contact": phone,
                    "receipt_no": "",
                    "sku": str(sku_s.iloc[i] or '') if 'SKU' in df.columns else "",
                })
            
            # 相手区分を「店舗」に設定
            if hasattr(self, 'cmb_counterparty'):
                idx_store = self.cmb_counterparty.findText('店舗')
                if idx_store >= 0:
                    self.cmb_counterparty.setCurrentIndex(idx_store)
            
            self._imported_store_rows = rows
            self._refresh_store_list_table()
            
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"データの取込でエラーが発生しました:\n{e}")

    def _on_store_list_selection_changed(self):
        """店舗リストの選択変更時に削除ボタンの有効/無効を切り替え"""
        try:
            selection_model = self.table_store_list.selectionModel()
            has_selection = bool(selection_model and selection_model.selectedRows())
            self.btn_delete_selected_store.setEnabled(has_selection)
            
            # リストにデータがある場合は全削除ボタンを有効化
            rows = getattr(self, "_imported_store_rows", [])
            self.btn_delete_all_store.setEnabled(len(rows) > 0)
        except Exception:
            pass
    
    def _delete_selected_store_rows(self):
        """選択された店舗リストの行を削除"""
        try:
            selection_model = self.table_store_list.selectionModel()
            if not selection_model:
                return
            
            selected_rows = selection_model.selectedRows()
            if not selected_rows:
                QMessageBox.information(self, "情報", "削除する行を選択してください。")
                return
            
            # 選択された行インデックスを降順でソート（後ろから削除することでインデックスがずれないようにする）
            row_indices = sorted([idx.row() for idx in selected_rows], reverse=True)
            
            # 確認ダイアログ
            reply = QMessageBox.question(
                self,
                "確認",
                f"選択された {len(row_indices)} 行を削除しますか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply != QMessageBox.Yes:
                return
            
            # データから削除
            rows = getattr(self, "_imported_store_rows", [])
            for idx in row_indices:
                if 0 <= idx < len(rows):
                    rows.pop(idx)
            
            # テーブルを再描画
            self._refresh_store_list_table()
            
            QMessageBox.information(self, "削除完了", f"{len(row_indices)} 行を削除しました。")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"削除中にエラーが発生しました:\n{e}")
    
    def _delete_all_store_rows(self):
        """店舗リストの全行を削除"""
        try:
            rows = getattr(self, "_imported_store_rows", [])
            if not rows:
                QMessageBox.information(self, "情報", "削除するデータがありません。")
                return
            
            # 確認ダイアログ
            reply = QMessageBox.question(
                self,
                "確認",
                f"リストの全 {len(rows)} 行を削除しますか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply != QMessageBox.Yes:
                return
            
            # データをクリア
            self._imported_store_rows = []
            
            # テーブルを再描画
            self._refresh_store_list_table()
            
            QMessageBox.information(self, "削除完了", "リストの全データを削除しました。")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"削除中にエラーが発生しました:\n{e}")
    
    def _refresh_store_list_table(self) -> None:
        try:
            rows = getattr(self, "_imported_store_rows", [])
            self.table_store_list.setRowCount(len(rows))
            
            # 削除ボタンの有効/無効を更新
            self.btn_delete_all_store.setEnabled(len(rows) > 0)
            self.btn_delete_selected_store.setEnabled(False)
            
            for i, r in enumerate(rows):
                for j, key in enumerate(self.preview_keys):
                    val = "" if r.get(key) is None else str(r.get(key))
                    # 取引日の場合は時刻部分を削除
                    if key == 'entry_date':
                        val = self._normalize_date(val)
                    # 品目は常にプルダウンで選択可能にする（マッチした品目も変更可能）
                    if key == 'kobutsu_kind':
                        cb = QComboBox()
                        cb.addItems(self.CATEGORY_CHOICES)
                        # 既存の値を設定（正規化してから）
                        if val:
                            normalized_val = self._normalize_category_name(val)
                            idx = cb.findText(normalized_val)
                            if idx >= 0:
                                cb.setCurrentIndex(idx)
                                # 初期表示時も内部データへ反映
                                try:
                                    self._imported_store_rows[i][key] = cb.currentText()
                                except Exception:
                                    pass
                            else:
                                # マッチしない場合はデフォルトで「道具類」
                                idx_tool = cb.findText("道具類")
                                if idx_tool >= 0:
                                    cb.setCurrentIndex(idx_tool)
                                    try:
                                        self._imported_store_rows[i][key] = cb.currentText()
                                    except Exception:
                                        pass
                        else:
                            # 値がない場合もデフォルトで「道具類」
                            idx_tool = cb.findText("道具類")
                            if idx_tool >= 0:
                                cb.setCurrentIndex(idx_tool)
                                try:
                                    self._imported_store_rows[i][key] = cb.currentText()
                                except Exception:
                                    pass
                        # 変更時にデータへ反映＋学習処理
                        def on_changed(idx, row_index=i, col_key=key, combo=cb):
                            try:
                                choice = combo.currentText()
                                self._imported_store_rows[row_index][col_key] = choice
                                # 学習処理: 商品名と識別情報から学習
                                row_data = self._imported_store_rows[row_index]
                                product_name = str(row_data.get('hinmei', '') or '')
                                identifier = str(row_data.get('identifier', '') or '')
                                if product_name and choice:
                                    self._learn_category_edit(product_name, choice, identifier)
                            except Exception as e:
                                print(f"学習処理エラー: {e}")
                        cb.currentIndexChanged.connect(on_changed)
                        self.table_store_list.setCellWidget(i, j, cb)
                    else:
                        self.table_store_list.setItem(i, j, QTableWidgetItem(val))
            self.table_store_list.resizeColumnsToContents()
        except Exception:
            pass

    def _commit_imported_store_rows(self) -> None:
        """取込プレビューの店舗行を、現在の共通テンプレ値と合成して台帳へ一括登録"""
        try:
            if self.cmb_counterparty.currentText() != '店舗':
                QMessageBox.warning(self, "相手区分", "相手区分を『店舗』にしてください。")
                return
            rows = getattr(self, '_imported_store_rows', [])
            if not rows:
                QMessageBox.information(self, "データなし", "取込プレビューに行がありません。")
                return

            # 取込プレビューの各行をチェック（テンプレートは不要）
            to_insert = []
            missing_rows = []
            for idx, r in enumerate(rows, start=1):
                # 各行の必須チェック
                missing = []
                if not str(r.get('hinmei', '')).strip():
                    missing.append("品名")
                if not str(r.get('identifier', '')).strip():
                    missing.append("識別情報")
                if not str(r.get('counterparty_name', '')).strip():
                    missing.append("仕入先名")
                if not str(r.get('kobutsu_kind', '')).strip():
                    missing.append("品目")
                
                if missing:
                    missing_rows.append(f"行{idx}: {', '.join(missing)}")
                    continue  # 必須項目が不足している行はスキップ
                # 取込行のデータを直接使用（テンプレートは補完のみ）
                qty_v = r.get('qty', 0) or 0
                unit_v = r.get('unit_price', 0) or 0
                amount_v = r.get('amount') or (int(qty_v) * int(unit_v))
                row = {
                    'entry_date': r.get('entry_date') or self.ed_entry_date.date().toString('yyyy-MM-dd'),
                    'counterparty_type': '店舗',
                    'counterparty_name': str(r.get('counterparty_name', '')).strip(),
                    'receipt_no': str(r.get('receipt_no', '')).strip() or None,
                    'platform': None,
                    'platform_order_id': None,
                    'platform_user': None,
                    'person_name': None,
                    'person_address': None,  # 店舗取引なので個人住所は常にNone
                    # 店舗用フィールドを正しく反映
                    'counterparty_branch': r.get('counterparty_branch') or None,
                    'counterparty_address': r.get('counterparty_address') or None,
                    'contact': r.get('contact') or None,
                    'id_type': None,
                    'id_number': None,
                    'id_checked_on': None,
                    'id_checked_by': None,
                    'id_proof_ref': None,
                    # 統合: 区分13=品目
                    'kobutsu_kind': str(r.get('kobutsu_kind', '')).strip(),
                    'hinmoku': str(r.get('kobutsu_kind', '')).strip(),
                    'hinmei': str(r.get('hinmei', '')).strip(),
                    'qty': int(qty_v),
                    'unit_price': int(unit_v),
                    'amount': int(amount_v),
                    'identifier': str(r.get('identifier', '')).strip(),
                    'transaction_method': '買受',
                    'notes': str(r.get('notes', '')).strip() or None,
                    'correction_of': None,
                    'sku': r.get('sku', ''),
                }
                to_insert.append(row)
            
            # 必須項目が不足している行がある場合は警告
            if missing_rows:
                msg = f"以下の行は必須項目が不足しているためスキップされました:\n" + "\n".join(missing_rows[:10])
                if len(missing_rows) > 10:
                    msg += f"\n...他{len(missing_rows) - 10}行"
                QMessageBox.warning(self, "一部スキップ", msg)

            if not to_insert:
                QMessageBox.information(self, "登録対象なし", "登録可能な行がありません（仕入先名の空行は除外されます）。")
                return

            from desktop.database.ledger_db import LedgerDatabase
            db = LedgerDatabase()
            n = db.insert_ledger_rows(to_insert)
            
            # 2. 仕入DB (purchases) の古物台帳情報も更新（統合対応）
            try:
                from desktop.database.purchase_db import PurchaseDatabase
                pdb = PurchaseDatabase()
                updated_purchases = 0
                for row in to_insert:
                    sku = row.get('sku')
                    if sku:
                        # 古物台帳情報を抽出
                        ledger_info = {
                            'kobutsu_kind': row.get('kobutsu_kind'),
                            'hinmoku': row.get('hinmoku'),
                            'hinmei': row.get('hinmei'),
                            'person_name': row.get('person_name'),
                            'id_type': row.get('id_type'),
                            'id_number': row.get('id_number'),
                            'id_checked_on': row.get('id_checked_on'),
                            'id_checked_by': row.get('id_checked_by'),
                        }
                        if pdb.update_ledger_info(sku, ledger_info):
                            updated_purchases += 1
                # print(f"仕入DB同期: {updated_purchases}件")
            except Exception as e:
                print(f"仕入DB同期エラー: {e}")
            
            self._imported_store_rows = []
            self._refresh_store_list_table()
            # 閲覧・出力タブを即時更新
            try:
                self.reload_ledger_rows()
            except Exception:
                pass
            QMessageBox.information(self, "登録完了", f"{n}件を台帳に登録しました。『閲覧・出力』で確認できます。")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"一括登録でエラーが発生しました:\n{e}")

    # ===== 閲覧・出力タブ（既存UIを移設） =====
    def _setup_tab_view(self):
        layout = QVBoxLayout(self.tab_view)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 上部：日付範囲選択エリア
        self.setup_date_range_selection(layout)

        # 中央：フィルタエリア
        self.setup_filter_area(layout)

        # 下部：データテーブルエリア
        self.setup_data_table(layout)

        # 最下部：アクションボタンエリア
        self.setup_action_buttons(layout)

        # 追加: 更新ボタンとキーワード検索
        tool_row = QHBoxLayout()
        self.btn_refresh = QPushButton("更新")
        self.btn_refresh.clicked.connect(self.reload_ledger_rows)
        tool_row.addWidget(self.btn_refresh)
        tool_row.addStretch()
        layout.addLayout(tool_row)

        # データ初期ロード
        self.antique_data = []
        self.reload_ledger_rows()
        
    def setup_date_range_selection(self, parent_layout=None):
        """日付範囲選択エリアの設定"""
        date_group = QGroupBox("日付範囲選択")
        date_layout = QHBoxLayout(date_group)
        
        # 開始日
        start_label = QLabel("開始日:")
        date_layout.addWidget(start_label)
        
        self.start_date_edit = QDateEdit()
        self.start_date_edit.setDate(QDate.currentDate().addDays(-30))  # 30日前をデフォルト
        self.start_date_edit.setCalendarPopup(True)
        date_layout.addWidget(self.start_date_edit)
        
        # 終了日
        end_label = QLabel("終了日:")
        date_layout.addWidget(end_label)
        
        self.end_date_edit = QDateEdit()
        self.end_date_edit.setDate(QDate.currentDate())  # 今日をデフォルト
        self.end_date_edit.setCalendarPopup(True)
        date_layout.addWidget(self.end_date_edit)
        
        # 古物台帳生成ボタン
        self.generate_btn = QPushButton("古物台帳生成")
        self.generate_btn.clicked.connect(self.generate_antique_register)
        self.generate_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """)
        date_layout.addWidget(self.generate_btn)
        
        date_layout.addStretch()
        
        (parent_layout or self.layout()).addWidget(date_group)
        
    def setup_filter_area(self, parent_layout=None):
        """フィルタエリアの設定"""
        filter_group = QGroupBox("フィルタ")
        filter_layout = QHBoxLayout(filter_group)
        
        # 検索ボックス
        search_label = QLabel("検索:")
        filter_layout.addWidget(search_label)
        
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("商品名、SKU、ASINで検索...")
        self.search_edit.textChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.search_edit)
        
        # 価格範囲フィルタ
        price_label = QLabel("価格範囲:")
        filter_layout.addWidget(price_label)
        
        self.min_price_spin = QSpinBox()
        self.min_price_spin.setRange(0, 999999)
        self.min_price_spin.setValue(0)
        self.min_price_spin.valueChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.min_price_spin)
        
        price_to_label = QLabel("〜")
        filter_layout.addWidget(price_to_label)
        
        self.max_price_spin = QSpinBox()
        self.max_price_spin.setRange(0, 999999)
        self.max_price_spin.setValue(999999)
        self.max_price_spin.valueChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.max_price_spin)
        
        # 相手区分フィルタ
        filter_layout.addWidget(QLabel("相手区分:"))
        self.cmb_counterparty_filter = QComboBox()
        self.cmb_counterparty_filter.addItems(["すべて", "店舗", "フリマ", "個人"])
        self.cmb_counterparty_filter.currentTextChanged.connect(self._on_counterparty_filter_changed)
        filter_layout.addWidget(self.cmb_counterparty_filter)

        # 列グループ表示トグル
        self.grp_toggles = QGroupBox("列グループ表示")
        toggles = QHBoxLayout(self.grp_toggles)
        self.chk_group_store = QCheckBox("店舗")
        self.chk_group_flea = QCheckBox("フリマ")
        self.chk_group_person = QCheckBox("個人")
        for cb in (self.chk_group_store, self.chk_group_flea, self.chk_group_person):
            cb.toggled.connect(self.apply_column_visibility)
            toggles.addWidget(cb)
        toggles.addStretch()
        filter_layout.addWidget(self.grp_toggles)

        # フィルタリセットボタン
        self.reset_filters_btn = QPushButton("フィルタリセット")
        self.reset_filters_btn.clicked.connect(self.reset_filters)
        filter_layout.addWidget(self.reset_filters_btn)
        
        filter_layout.addStretch()
        
        (parent_layout or self.layout()).addWidget(filter_group)
        
    def setup_data_table(self, parent_layout=None):
        """データテーブルエリアの設定"""
        # テーブルウィジェットの作成（統一スキーマ列）
        self.data_table = QTableWidget()
        self.data_table.setAlternatingRowColors(True)
        self.data_table.setSelectionBehavior(QTableWidget.SelectRows)
        
        # ヘッダーの設定
        header = self.data_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.Interactive)
        # 列幅保存/復元
        header.sectionResized.connect(self._save_column_widths)
        
        # 統一スキーマの見出し（日本語）
        self.column_headers = [label for _, label in self.ALL_COLUMNS]
        self.column_keys = [key for key, _ in self.ALL_COLUMNS]
        self.data_table.setColumnCount(len(self.column_headers))
        self.data_table.setHorizontalHeaderLabels(self.column_headers)
        self._load_column_widths()
        
        # テーブルをレイアウトに追加
        (parent_layout or self.layout()).addWidget(self.data_table)
        # 品名列は省略表示（50文字）＋選択時は全表示
        try:
            self.data_table.itemSelectionChanged.connect(self._on_table_selection_changed)
        except Exception:
            pass
        
    def setup_action_buttons(self, parent_layout=None):
        """アクションボタンエリアの設定"""
        action_layout = QHBoxLayout()
        
        # CSV出力ボタン
        self.export_csv_btn = QPushButton("CSV出力")
        self.export_csv_btn.clicked.connect(self.export_csv)
        self.export_csv_btn.setEnabled(False)
        self.export_csv_btn.setStyleSheet("""
            QPushButton {
                background-color: #007bff;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0056b3;
            }
        """)
        action_layout.addWidget(self.export_csv_btn)
        
        # Excel出力ボタン
        self.export_excel_btn = QPushButton("Excel出力")
        self.export_excel_btn.clicked.connect(self.export_excel)
        self.export_excel_btn.setEnabled(False)
        action_layout.addWidget(self.export_excel_btn)
        
        # データクリアボタン
        self.clear_btn = QPushButton("データクリア")
        self.clear_btn.clicked.connect(self.clear_data)
        self.clear_btn.setEnabled(False)
        action_layout.addWidget(self.clear_btn)

        # デバッグ: 全データ削除
        self.debug_delete_btn = QPushButton("全データ削除(デバッグ)")
        self.debug_delete_btn.clicked.connect(self._debug_delete_all_data)
        self.debug_delete_btn.setStyleSheet("color: #b00;")
        action_layout.addWidget(self.debug_delete_btn)
        
        action_layout.addStretch()
        
        # 統計情報表示
        self.stats_label = QLabel("統計: なし")
        action_layout.addWidget(self.stats_label)
        
        # 進捗バー
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumHeight(25)
        action_layout.addWidget(self.progress_bar)
        
        (parent_layout or self.layout()).addLayout(action_layout)
        
    def generate_antique_register(self):
        """古物台帳の生成"""
        # 日付の取得
        start_date = self.start_date_edit.date().toString("yyyy-MM-dd")
        end_date = self.end_date_edit.date().toString("yyyy-MM-dd")
        
        # 日付の妥当性チェック
        if start_date > end_date:
            QMessageBox.warning(self, "エラー", "開始日は終了日より前である必要があります")
            return
            
        # 進捗バーの表示
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.generate_btn.setEnabled(False)
        
        # ワーカースレッドの作成と実行
        self.worker = AntiqueWorker(start_date, end_date, self.api_client)
        self.worker.progress_updated.connect(self.progress_bar.setValue)
        self.worker.result_ready.connect(self.on_generation_completed)
        self.worker.error_occurred.connect(self.on_generation_error)
        self.worker.start()
        
    def on_generation_completed(self, result):
        """古物台帳生成完了時の処理"""
        self.progress_bar.setVisible(False)
        self.generate_btn.setEnabled(True)
        
        if result['status'] == 'success':
            # 生成結果はDBに反映済み前提。画面はDBから再読み込みして維持する
            try:
                self.reload_ledger_rows()
            except Exception:
                pass
            # ボタンの有効化
            self.export_csv_btn.setEnabled(True)
            self.export_excel_btn.setEnabled(True)
            self.clear_btn.setEnabled(True)
            # 統計情報更新
            self.update_stats()
            QMessageBox.information(
                self,
                "古物台帳生成完了",
                f"古物台帳生成が完了しました\n期間: {result.get('period','-')}\n件数: {result.get('total_items','-')}件"
            )
        else:
            QMessageBox.warning(self, "古物台帳生成失敗", "古物台帳生成に失敗しました")
            
    def on_generation_error(self, error_message):
        """古物台帳生成エラー時の処理"""
        self.progress_bar.setVisible(False)
        self.generate_btn.setEnabled(True)
        
        QMessageBox.critical(self, "エラー", f"古物台帳生成に失敗しました:\n{error_message}")
        
    def update_table(self):
        """テーブルの更新"""
        if self.antique_data is None:
            return
            
        # テーブルの設定
        self.data_table.setRowCount(len(self.antique_data))
        
        # データの設定
        for i, item in enumerate(self.antique_data):
            for j, key in enumerate(self.column_keys):
                raw = item.get(key, "")
                value = "" if raw is None else str(raw)
                # 取引日の場合は時刻部分を削除
                if key == "entry_date":
                    value = self._normalize_date(value)
                display_value = value
                if key == 'hinmei' and value:
                    # 50文字にトリム
                    display_value = (value[:50] + '…') if len(value) > 50 else value
                item_widget = QTableWidgetItem(display_value)
                if key == 'hinmei':
                    # ツールチップは常にフルテキスト
                    item_widget.setToolTip(value)
                    # フルテキストをUserRoleに保持
                    item_widget.setData(Qt.UserRole, value)
                
                # 金額/数量などの簡易フォーマット
                header_label = self.column_headers[j]
                if header_label in ["数量", "単価", "金額"] and value.replace(".", "").isdigit():
                    try:
                        num_value = float(value)
                        item_widget.setText(f"{num_value:,.0f}")
                    except:
                        pass

                # ツールチップはフルテキスト（他列も同様）
                if not item_widget.toolTip():
                    item_widget.setToolTip(value)
                
                self.data_table.setItem(i, j, item_widget)
        
        # 列幅の自動調整
        self.data_table.resizeColumnsToContents()
        # 列表示の適用
        self.apply_column_visibility()

    def _on_table_selection_changed(self):
        try:
            # まずすべてをトリム表示に戻す
            if not hasattr(self, 'column_keys'):
                return
            hinmei_col = None
            for idx, key in enumerate(self.column_keys):
                if key == 'hinmei':
                    hinmei_col = idx
                    break
            if hinmei_col is None:
                return
            for r in range(self.data_table.rowCount()):
                item = self.data_table.item(r, hinmei_col)
                if not item:
                    continue
                full = item.data(Qt.UserRole) or item.text()
                trimmed = (full[:50] + '…') if len(full) > 50 else full
                item.setText(trimmed)
            # 選択行はフル表示
            if self.data_table.selectionModel():
                for idx in self.data_table.selectionModel().selectedRows():
                    item = self.data_table.item(idx.row(), hinmei_col)
                    if item:
                        full = item.data(Qt.UserRole) or item.text()
                        item.setText(full)
        except Exception:
            pass
        
    def apply_filters(self):
        """フィルタの適用"""
        if self.antique_data is None:
            return
            
        # 検索条件
        search_text = self.search_edit.text().lower()
        
        # 価格範囲フィルタ
        min_price = self.min_price_spin.value()
        max_price = self.max_price_spin.value()
        
        # フィルタの適用
        filtered_data = []
        for item in self.antique_data:
            # 検索フィルタ
            if search_text:
                search_match = (
                    search_text in str(item.get("商品名", "")).lower() or
                    search_text in str(item.get("SKU", "")).lower() or
                    search_text in str(item.get("ASIN", "")).lower()
                )
                if not search_match:
                    continue
            
            # 価格範囲フィルタ
            try:
                price = float(item.get("価格", 0))
                if price < min_price or price > max_price:
                    continue
            except:
                pass
            
            filtered_data.append(item)
        
        # フィルタ結果でテーブルを更新
        self.update_table_with_filtered_data(filtered_data)
        
    def update_table_with_filtered_data(self, filtered_data):
        """フィルタ結果でテーブルを更新"""
        # テーブルの設定
        self.data_table.setRowCount(len(filtered_data))
        
        # データの設定
        for i, item in enumerate(filtered_data):
            for j, key in enumerate(self.column_keys):
                raw = item.get(key, "")
                value = "" if raw is None else str(raw)
                # 取引日の場合は時刻部分を削除
                if key == "entry_date":
                    value = self._normalize_date(value)
                display_value = value
                if key == 'hinmei' and value:
                    display_value = (value[:50] + '…') if len(value) > 50 else value
                item_widget = QTableWidgetItem(display_value)
                if key == 'hinmei':
                    item_widget.setToolTip(value)
                    item_widget.setData(Qt.UserRole, value)
                
                header_label = self.column_headers[j]
                if header_label in ["数量", "単価", "金額"] and value.replace(".", "").isdigit():
                    try:
                        num_value = float(value)
                        item_widget.setText(f"{num_value:,.0f}")
                    except:
                        pass
                if not item_widget.toolTip():
                    item_widget.setToolTip(value)
                
                self.data_table.setItem(i, j, item_widget)
        
        # 列幅の自動調整
        self.data_table.resizeColumnsToContents()
        self.apply_column_visibility()

    # === データ取得/フィルタ ===
    def reload_ledger_rows(self):
        try:
            from desktop.database.ledger_db import LedgerDatabase
            db = LedgerDatabase()
            # 期間フィルタ値取得
            start = self.start_date_edit.date().toString('yyyy-MM-dd') if hasattr(self, 'start_date_edit') else None
            end = self.end_date_edit.date().toString('yyyy-MM-dd') if hasattr(self, 'end_date_edit') else None
            where = []
            params = []
            if start:
                where.append("entry_date >= ?")
                params.append(start)
            if end:
                where.append("entry_date <= ?")
                params.append(end)
            rows = db.query_ledger(" AND ".join(where), tuple(params))
            self.antique_data = rows
            self.apply_filters()
        except Exception as e:
            print(f"台帳ロード失敗: {e}")

    def get_filtered_rows(self):
        rows = self.antique_data or []
        # 相手区分フィルタ
        cpt = getattr(self, 'cmb_counterparty_filter', None)
        if cpt and cpt.currentText() != 'すべて':
            rows = [r for r in rows if str(r.get('counterparty_type','')) == cpt.currentText()]
        # キーワード（既存の検索ボックス使用）
        keyword = self.search_edit.text().strip().lower() if hasattr(self, 'search_edit') else ''
        if keyword:
            def hit(r):
                for k in [k for k,_ in self.ALL_COLUMNS]:
                    v = str(r.get(k, '')).lower()
                    if keyword in v:
                        return True
                return False
            rows = [r for r in rows if hit(r)]
        return rows

    def apply_filters(self):
        rows = self.get_filtered_rows()
        # テーブルへ反映
        self.update_table_with_filtered_data(rows)
        
    def reset_filters(self):
        """フィルタのリセット"""
        self.search_edit.clear()
        self.min_price_spin.setValue(0)
        self.max_price_spin.setValue(999999)
        if hasattr(self, 'cmb_counterparty_filter'):
            self.cmb_counterparty_filter.setCurrentIndex(0)
        if hasattr(self, 'chk_group_store'):
            self.chk_group_store.setChecked(False)
        if hasattr(self, 'chk_group_flea'):
            self.chk_group_flea.setChecked(False)
        if hasattr(self, 'chk_group_person'):
            self.chk_group_person.setChecked(False)
        
        # 元のデータでテーブルを更新
        if self.antique_data:
            self.update_table()
            
    def update_stats(self, result=None):
        """統計情報の更新"""
        if self.antique_data is None:
            self.stats_label.setText("統計: なし")
            return
            
        # 基本統計
        total_items = len(self.antique_data)
        
        # 価格統計
        try:
            prices = [float(item.get("価格", 0)) for item in self.antique_data if item.get("価格")]
            if prices:
                avg_price = sum(prices) / len(prices)
                total_value = sum(prices)
                price_stats = f"平均価格: {avg_price:,.0f}円, 合計: {total_value:,.0f}円"
            else:
                price_stats = "価格統計: なし"
        except:
            price_stats = "価格統計: エラー"
        
        stats_text = f"統計: {total_items}件, {price_stats}"
        self.stats_label.setText(stats_text)
        
    def clear_data(self):
        """データのクリア"""
        self.antique_data = None
        self.data_table.setRowCount(0)
        
        # ボタンの無効化
        self.export_csv_btn.setEnabled(False)
        self.export_excel_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        
        # 表示のクリア
        self.stats_label.setText("統計: なし")

    def _debug_delete_all_data(self):
        """DB全削除（デバッグ）"""
        ret = QMessageBox.question(self, "全データ削除", "ledger_entries等の全データを削除します。よろしいですか？", QMessageBox.Yes | QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        try:
            from desktop.database.ledger_db import LedgerDatabase
            db = LedgerDatabase()
            db.delete_all()
            self.clear_data()
            QMessageBox.information(self, "削除完了", "全データを削除しました。")
        except Exception as e:
            QMessageBox.critical(self, "削除失敗", f"削除に失敗しました:\n{e}")
        
    def export_csv(self):
        """CSV出力"""
        if self.antique_data is None:
            QMessageBox.warning(self, "エラー", "出力するデータがありません")
            return
            
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "古物台帳CSVファイルを保存",
            f"antique_register_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            "CSVファイル (*.csv)"
        )
        
        if file_path:
            try:
                # フィルタ結果を出力（0件ならDBから再読込して再取得）
                rows = self.get_filtered_rows()
                if not rows:
                    try:
                        self.reload_ledger_rows()
                        rows = self.get_filtered_rows()
                    except Exception:
                        pass
                from pathlib import Path
                from desktop.utils.file_naming import resolve_unique_path
                target = resolve_unique_path(Path(file_path))

                import csv
                with open(str(target), 'w', encoding='cp932', newline='') as f:
                    w = csv.writer(f, lineterminator='\r\n', quoting=csv.QUOTE_ALL, doublequote=True)
                    # 日本語ヘッダ
                    w.writerow(self.column_headers)
                    for r in rows:
                        row_out = ["" if r.get(k) is None else str(r.get(k)) for k in self.column_keys]
                        w.writerow(row_out)
                
                QMessageBox.information(self, "出力完了", f"CSVファイルを保存しました:\n{str(target)}")
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"保存に失敗しました:\n{str(e)}")

    # === 列幅保存/復元 ===
    def _settings(self) -> QSettings:
        return QSettings("HIRIO", "SedoriDesktopApp")

    def _save_column_widths(self, *_):
        try:
            s = self._settings()
            widths = [self.data_table.columnWidth(i) for i in range(self.data_table.columnCount())]
            s.setValue("ledger/column_widths", widths)
        except Exception:
            pass

    def _load_column_widths(self):
        try:
            s = self._settings()
            widths = s.value("ledger/column_widths", None)
            if widths:
                for i, w in enumerate(widths):
                    try:
                        self.data_table.setColumnWidth(i, int(w))
                    except Exception:
                        continue
        except Exception:
            pass

    def apply_column_visibility(self):
        """列グループの表示/非表示を適用（共通は常時表示）"""
        try:
            # マップ: key -> index
            key_to_index = {k: i for i, k in enumerate(self.column_keys)}
            # まず全列を非表示にせず、状態を決める
            # 共通は常時表示
            for k, _ in self.COMMON_COLUMNS:
                self.data_table.setColumnHidden(key_to_index[k], False)
            # グループはトグル
            for k, _ in self.STORE_COLUMNS:
                self.data_table.setColumnHidden(key_to_index[k], not self.chk_group_store.isChecked())
            for k, _ in self.FLEA_COLUMNS:
                self.data_table.setColumnHidden(key_to_index[k], not self.chk_group_flea.isChecked())
            for k, _ in self.PERSON_COLUMNS:
                self.data_table.setColumnHidden(key_to_index[k], not self.chk_group_person.isChecked())
        except Exception as e:
            print(f"列可視化エラー: {e}")

    def _on_counterparty_filter_changed(self, text: str):
        # 相手区分フィルタ選択に応じてグループトグルを自動ON/OFF
        if text == '店舗':
            self.chk_group_store.setChecked(True)
            self.chk_group_flea.setChecked(False)
            self.chk_group_person.setChecked(False)
        elif text == 'フリマ':
            self.chk_group_store.setChecked(False)
            self.chk_group_flea.setChecked(True)
            self.chk_group_person.setChecked(False)
        elif text == '個人':
            self.chk_group_store.setChecked(False)
            self.chk_group_flea.setChecked(False)
            self.chk_group_person.setChecked(True)
        else:
            # すべて
            self.chk_group_store.setChecked(False)
            self.chk_group_flea.setChecked(False)
            self.chk_group_person.setChecked(False)
                
    def export_excel(self):
        """Excel出力"""
        if self.antique_data is None:
            QMessageBox.warning(self, "エラー", "出力するデータがありません")
            return
            
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "古物台帳Excelファイルを保存",
            f"antique_register_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            "Excelファイル (*.xlsx)"
        )
        
        if file_path:
            try:
                # フィルタ結果を出力（0件ならDBから再読込して再取得）
                rows = self.get_filtered_rows()
                if not rows:
                    try:
                        self.reload_ledger_rows()
                        rows = self.get_filtered_rows()
                    except Exception:
                        pass
                from pathlib import Path
                from desktop.utils.file_naming import resolve_unique_path
                target = resolve_unique_path(Path(file_path))
                
                # 日本語ヘッダーと正しい順序でデータフレームを作成
                data_for_df = []
                for r in rows:
                    row_dict = {}
                    for key, header in zip(self.column_keys, self.column_headers):
                        value = r.get(key)
                        # Noneは空文字に変換
                        row_dict[header] = "" if value is None else str(value)
                    data_for_df.append(row_dict)
                
                df = pd.DataFrame(data_for_df)
                # 列の順序を日本語ヘッダーの順序に合わせる
                df = df[self.column_headers]
                df.to_excel(str(target), index=False, engine='openpyxl')
                
                QMessageBox.information(self, "出力完了", f"Excelファイルを保存しました:\n{str(target)}")
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"保存に失敗しました:\n{str(e)}")

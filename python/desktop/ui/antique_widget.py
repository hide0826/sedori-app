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
        # 統一スキーマ（列キー→日本語見出し）
        self.COMMON_COLUMNS = [
            ("entry_date", "取引日"),
            ("kobutsu_kind", "区分13"),
            ("hinmoku", "品目"),
            ("hinmei", "品名"),
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
            ("counterparty_address", "住所"),
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
            ("person_address", "住所"),
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
        self.tabs.addTab(self.tab_input, "入力・生成")
        self.tabs.addTab(self.tab_view, "閲覧・出力")

        root = QVBoxLayout(self)
        root.addWidget(self.tabs)

        # それぞれのタブを構築（列スキーマ定義後に呼ぶ）
        self._setup_tab_input()
        self._setup_tab_view()
        
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
        self.cmb_kobutsu = QComboBox(); self.cmb_kobutsu.addItems(["衣類","皮革・ゴム製品類","金属製品類","家具","什器類","電機機械類（道具類）","自動車","自動二輪車・原付","自転車類","書籍","CD・DVD・BD等","ゲーム・玩具","時計・宝飾品類"]) 
        g.addWidget(QLabel("13区分"), row, 0); g.addWidget(self.cmb_kobutsu, row, 1); row += 1
        self.ed_hinmoku = QLineEdit(); g.addWidget(QLabel("品目"), row, 0); g.addWidget(self.ed_hinmoku, row, 1); row += 1
        self.ed_hinmei = QLineEdit(); g.addWidget(QLabel("品名"), row, 0); g.addWidget(self.ed_hinmei, row, 1); row += 1
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
        self.table_store_list = QTableWidget()
        self.table_store_list.setAlternatingRowColors(True)
        self.table_store_list.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_store_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
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
        self.btn_commit_bulk.setEnabled(False)
        actions.addWidget(self.btn_draft)
        actions.addWidget(self.btn_commit)
        actions.addWidget(self.btn_commit_bulk)
        actions.addStretch()
        lay.addLayout(actions)

        # イベント
        self.btn_commit.clicked.connect(self._commit_single_row)
        self.cmb_counterparty.currentTextChanged.connect(self._on_counterparty_changed)
        self.btn_import_store.clicked.connect(self._on_import_store_clicked)
        self.btn_toggle_template.toggled.connect(self._on_toggle_template)
        self.btn_commit_bulk.clicked.connect(self._commit_imported_store_rows)
        self._on_counterparty_changed(self.cmb_counterparty.currentText())

        # 取込データ保持
        self._imported_store_rows = []

    def _commit_single_row(self):
        """フォーム1行をバリデーションして ledger_entries に保存"""
        from desktop.database.ledger_db import LedgerDatabase
        # 必須チェック（最低限）
        missing = []
        if not self.ed_hinmoku.text().strip(): missing.append("品目")
        if not self.ed_hinmei.text().strip(): missing.append("品名")
        if not self.ed_identifier.text().strip(): missing.append("識別情報")
        cp = self.cmb_counterparty.currentText()
        if cp == '店舗':
            if not self.ed_counterparty.text().strip(): missing.append("仕入先名")
            if not self.ed_receipt.text().strip(): missing.append("レシート番号")
        elif cp == 'フリマ':
            if not self.ed_counterparty.text().strip(): missing.append("ユーザー名")
            if not self.ed_receipt.text().strip(): missing.append("取引ID")
        elif cp == '個人':
            if not self.ed_counterparty.text().strip(): missing.append("氏名")
            if not self.ed_receipt.text().strip(): missing.append("本人確認番号")
        if missing:
            QMessageBox.warning(self, "必須未入力", f"次を入力してください: {', '.join(missing)}")
            return

        qty = int(self.sp_qty.value()); unit = int(self.sp_unit.value()); amount = qty * unit
        row = {
            'entry_date': self.ed_entry_date.date().toString('yyyy-MM-dd'),
            'counterparty_type': cp,
            'counterparty_name': self.ed_counterparty.text().strip() if cp in ('店舗','個人') else None,
            'receipt_no': self.ed_receipt.text().strip() if cp == '店舗' else None,
            'platform': 'フリマ' if cp == 'フリマ' else None,
            'platform_order_id': self.ed_receipt.text().strip() if cp == 'フリマ' else None,
            'platform_user': self.ed_counterparty.text().strip() if cp == 'フリマ' else None,
            'person_name': self.ed_counterparty.text().strip() if cp == '個人' else None,
            'person_address': None,
            'id_type': 'ID',
            'id_number': self.ed_receipt.text().strip() if cp == '個人' else None,
            'id_checked_on': None,
            'id_checked_by': None,
            'id_proof_ref': None,
            'kobutsu_kind': self.cmb_kobutsu.currentText(),
            'hinmoku': self.ed_hinmoku.text().strip(),
            'hinmei': self.ed_hinmei.text().strip(),
            'qty': qty,
            'unit_price': unit,
            'amount': amount,
            'identifier': self.ed_identifier.text().strip(),
            'notes': None,
            'correction_of': None
        }
        db = LedgerDatabase()
        db.insert_ledger_rows([row])
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
            notes_s = pick_series("コメント")
            name_s = pick_series("仕入先")

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
                rows.append({
                    # 共通列
                    "entry_date": str(date_s.iloc[i]),
                    "kobutsu_kind": "",
                    "hinmoku": "",
                    "hinmei": str(title_s.iloc[i]),
                    "qty": qty_v,
                    "unit_price": unit_v,
                    "amount": amount_v,
                    "identifier": identifier_v,
                    "counterparty_type": "店舗",
                    "notes": str(notes_s.iloc[i]),
                    # 店舗列（支店/住所/連絡先/レシート番号は不明のため空）
                    "counterparty_name": str(name_s.iloc[i]),
                    "counterparty_branch": "",
                    "counterparty_address": "",
                    "contact": "",
                    "receipt_no": "",
                })

            self._imported_store_rows = rows
            self._refresh_store_list_table()
            self.btn_commit_bulk.setEnabled(self.cmb_counterparty.currentText() == '店舗' and len(rows) > 0)
            QMessageBox.information(self, "取込完了", f"仕入管理から {len(rows)} 件を取り込みました。")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"取込でエラーが発生しました:\n{e}")

    def _refresh_store_list_table(self) -> None:
        try:
            rows = getattr(self, "_imported_store_rows", [])
            self.table_store_list.setRowCount(len(rows))
            for i, r in enumerate(rows):
                for j, key in enumerate(self.preview_keys):
                    val = "" if r.get(key) is None else str(r.get(key))
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

            # 必須（共通）チェック
            missing = []
            if not self.ed_hinmoku.text().strip(): missing.append("品目")
            if not self.ed_hinmei.text().strip(): missing.append("品名")
            if not self.ed_identifier.text().strip(): missing.append("識別情報")
            if missing:
                QMessageBox.warning(self, "必須未入力", f"次を入力してください: {', '.join(missing)}")
                return

            to_insert = []
            for r in rows:
                if not str(r.get('counterparty_name', '')).strip():
                    continue
                # 取込行の値を優先。空の場合はテンプレ（コンボボックス等）で補完
                qty_v = r.get('qty') if r.get('qty') not in (None, "") else int(self.sp_qty.value())
                unit_v = r.get('unit_price') if r.get('unit_price') not in (None, "") else int(self.sp_unit.value())
                amount_v = r.get('amount') if r.get('amount') not in (None, "") else int(qty_v) * int(unit_v)
                row = {
                    'entry_date': r.get('entry_date') or self.ed_entry_date.date().toString('yyyy-MM-dd'),
                    'counterparty_type': '店舗',
                    'counterparty_name': r.get('counterparty_name'),
                    'receipt_no': r.get('receipt_no'),
                    'platform': None,
                    'platform_order_id': None,
                    'platform_user': None,
                    'person_name': None,
                    'person_address': None,
                    'id_type': None,
                    'id_number': None,
                    'id_checked_on': None,
                    'id_checked_by': None,
                    'id_proof_ref': None,
                    'kobutsu_kind': r.get('kobutsu_kind') or self.cmb_kobutsu.currentText(),
                    'hinmoku': r.get('hinmoku') or self.ed_hinmoku.text().strip(),
                    'hinmei': r.get('hinmei') or self.ed_hinmei.text().strip(),
                    'qty': int(qty_v),
                    'unit_price': int(unit_v),
                    'amount': int(amount_v),
                    'identifier': r.get('identifier') or self.ed_identifier.text().strip(),
                    'notes': r.get('notes') or None,
                    'correction_of': None,
                }
                to_insert.append(row)

            if not to_insert:
                QMessageBox.information(self, "登録対象なし", "登録可能な行がありません（仕入先名の空行は除外されます）。")
                return

            from desktop.database.ledger_db import LedgerDatabase
            db = LedgerDatabase()
            n = db.insert_ledger_rows(to_insert)
            self._imported_store_rows = []
            self._refresh_store_list_table()
            self.btn_commit_bulk.setEnabled(False)
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
            # データの保存
            self.antique_data = result['items']
            
            # テーブルの更新
            self.update_table()
            
            # ボタンの有効化
            self.export_csv_btn.setEnabled(True)
            self.export_excel_btn.setEnabled(True)
            self.clear_btn.setEnabled(True)
            
            # 統計情報の更新
            self.update_stats(result)
            
            QMessageBox.information(
                self, 
                "古物台帳生成完了", 
                f"古物台帳生成が完了しました\n期間: {result['period']}\n件数: {result['total_items']}件\n合計金額: {result['total_value']:,}円"
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
                value = str(item.get(key, ""))
                item_widget = QTableWidgetItem(value)
                
                # 金額/数量などの簡易フォーマット
                header_label = self.column_headers[j]
                if header_label in ["数量", "単価", "金額"] and value.replace(".", "").isdigit():
                    try:
                        num_value = float(value)
                        item_widget.setText(f"{num_value:,.0f}")
                    except:
                        pass

                # 長文はツールチップ
                if len(value) > 28:
                    item_widget.setToolTip(value)
                
                self.data_table.setItem(i, j, item_widget)
        
        # 列幅の自動調整
        self.data_table.resizeColumnsToContents()
        # 列表示の適用
        self.apply_column_visibility()
        
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
                value = str(item.get(key, ""))
                item_widget = QTableWidgetItem(value)
                
                header_label = self.column_headers[j]
                if header_label in ["数量", "単価", "金額"] and value.replace(".", "").isdigit():
                    try:
                        num_value = float(value)
                        item_widget.setText(f"{num_value:,.0f}")
                    except:
                        pass
                if len(value) > 28:
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
                # フィルタ結果を出力
                rows = self.get_filtered_rows()
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
                # データフレームの作成
                df = pd.DataFrame(self.antique_data)
                from pathlib import Path
                from desktop.utils.file_naming import resolve_unique_path
                target = resolve_unique_path(Path(file_path))
                df.to_excel(str(target), index=False, engine='openpyxl')
                
                QMessageBox.information(self, "出力完了", f"Excelファイルを保存しました:\n{str(target)}")
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"保存に失敗しました:\n{str(e)}")

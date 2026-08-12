#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""古物台帳（閲覧・出力）の行詳細編集ダイアログ。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import QDate, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() == "none":
        return ""
    return text


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return default


class LedgerEntryEditDialog(QDialog):
    """古物台帳1行の詳細編集。"""

    COUNTERPARTY_OPTIONS = ("法人", "フリマ", "個人")

    def __init__(
        self,
        record: Dict[str, Any],
        *,
        category_choices: Optional[List[str]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._record = dict(record or {})
        self._category_choices = list(category_choices or [])
        self.setWindowTitle("古物台帳 行の詳細編集")
        self.setMinimumWidth(560)
        self.resize(640, 720)
        self._build_ui()
        self._load_record()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        form = QFormLayout(body)
        form.setLabelAlignment(Qt.AlignRight)

        self.entry_date_edit = QDateEdit()
        self.entry_date_edit.setCalendarPopup(True)
        self.entry_date_edit.setDisplayFormat("yyyy-MM-dd")
        form.addRow("取引日:", self.entry_date_edit)

        self.kobutsu_combo = QComboBox()
        self.kobutsu_combo.setEditable(True)
        if self._category_choices:
            self.kobutsu_combo.addItems(self._category_choices)
        form.addRow("品目:", self.kobutsu_combo)

        self.hinmei_edit = QLineEdit()
        form.addRow("品名:", self.hinmei_edit)

        self.transaction_method_edit = QLineEdit()
        self.transaction_method_edit.setPlaceholderText("買受")
        form.addRow("取引方法:", self.transaction_method_edit)

        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(0, 99999)
        self.qty_spin.valueChanged.connect(self._recalc_amount)
        form.addRow("数量:", self.qty_spin)

        self.unit_price_spin = QSpinBox()
        self.unit_price_spin.setRange(0, 100_000_000)
        self.unit_price_spin.setGroupSeparatorShown(True)
        self.unit_price_spin.valueChanged.connect(self._recalc_amount)
        form.addRow("単価:", self.unit_price_spin)

        self.amount_spin = QSpinBox()
        self.amount_spin.setRange(0, 100_000_000)
        self.amount_spin.setGroupSeparatorShown(True)
        form.addRow("金額:", self.amount_spin)

        self.identifier_edit = QLineEdit()
        self.identifier_edit.setPlaceholderText("JAN / ASIN / シリアルなど")
        form.addRow("識別情報:", self.identifier_edit)

        self.sku_edit = QLineEdit()
        form.addRow("SKU:", self.sku_edit)

        self.counterparty_combo = QComboBox()
        self.counterparty_combo.addItems(self.COUNTERPARTY_OPTIONS)
        form.addRow("相手区分:", self.counterparty_combo)

        self.notes_edit = QLineEdit()
        form.addRow("備考:", self.notes_edit)

        store_box = QGroupBox("法人・店舗")
        store_form = QFormLayout(store_box)
        self.counterparty_name_edit = QLineEdit()
        store_form.addRow("仕入先名:", self.counterparty_name_edit)
        self.counterparty_branch_edit = QLineEdit()
        store_form.addRow("支店:", self.counterparty_branch_edit)
        self.counterparty_address_edit = QLineEdit()
        store_form.addRow("店舗住所:", self.counterparty_address_edit)
        self.contact_edit = QLineEdit()
        store_form.addRow("連絡先:", self.contact_edit)

        receipt_row = QHBoxLayout()
        self.receipt_no_edit = QLineEdit()
        self.receipt_no_edit.setPlaceholderText("https://... （レシート画像のURL）")
        open_btn = QPushButton("URLを開く")
        open_btn.setToolTip("入力中のレシート画像URLをブラウザで開きます")
        open_btn.clicked.connect(self._open_receipt_url)
        receipt_row.addWidget(self.receipt_no_edit, 1)
        receipt_row.addWidget(open_btn, 0)
        store_form.addRow("レシート画像URL:", receipt_row)
        form.addRow(store_box)

        flea_box = QGroupBox("フリマ")
        flea_form = QFormLayout(flea_box)
        self.platform_edit = QLineEdit()
        flea_form.addRow("プラットフォーム:", self.platform_edit)
        self.platform_order_id_edit = QLineEdit()
        flea_form.addRow("取引ID:", self.platform_order_id_edit)
        self.platform_user_edit = QLineEdit()
        flea_form.addRow("ユーザー名:", self.platform_user_edit)
        form.addRow(flea_box)

        person_box = QGroupBox("個人")
        person_form = QFormLayout(person_box)
        self.person_name_edit = QLineEdit()
        person_form.addRow("氏名:", self.person_name_edit)
        self.person_address_edit = QLineEdit()
        person_form.addRow("個人住所:", self.person_address_edit)
        self.id_type_edit = QLineEdit()
        person_form.addRow("本人確認種別:", self.id_type_edit)
        self.id_number_edit = QLineEdit()
        person_form.addRow("番号:", self.id_number_edit)
        self.id_checked_on_edit = QLineEdit()
        person_form.addRow("確認日:", self.id_checked_on_edit)
        self.id_checked_by_edit = QLineEdit()
        person_form.addRow("確認者:", self.id_checked_by_edit)
        self.id_proof_ref_edit = QLineEdit()
        person_form.addRow("証憑参照:", self.id_proof_ref_edit)
        form.addRow(person_box)

        hint = QLabel("保存すると古物台帳DBに反映され、一覧が更新されます。")
        hint.setStyleSheet("color: #888;")
        hint.setWordWrap(True)
        form.addRow(hint)

        scroll.setWidget(body)
        root.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("キャンセル")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _load_record(self) -> None:
        r = self._record
        date_text = _as_str(r.get("entry_date"))
        qdate = QDate.fromString(date_text[:10], "yyyy-MM-dd") if date_text else QDate()
        if qdate.isValid():
            self.entry_date_edit.setDate(qdate)
        else:
            self.entry_date_edit.setDate(QDate.currentDate())

        kind = _as_str(r.get("kobutsu_kind") or r.get("hinmoku"))
        if kind:
            idx = self.kobutsu_combo.findText(kind)
            if idx < 0:
                self.kobutsu_combo.addItem(kind)
                idx = self.kobutsu_combo.findText(kind)
            self.kobutsu_combo.setCurrentIndex(max(0, idx))

        self.hinmei_edit.setText(_as_str(r.get("hinmei")))
        self.transaction_method_edit.setText(_as_str(r.get("transaction_method")) or "買受")
        self.qty_spin.setValue(_as_int(r.get("qty"), 1))
        self.unit_price_spin.setValue(_as_int(r.get("unit_price"), 0))
        amount = r.get("amount")
        if amount is None or amount == "":
            self.amount_spin.setValue(self.qty_spin.value() * self.unit_price_spin.value())
        else:
            self.amount_spin.setValue(_as_int(amount, 0))
        self.identifier_edit.setText(_as_str(r.get("identifier")))
        self.sku_edit.setText(_as_str(r.get("sku")))

        cp = _as_str(r.get("counterparty_type")) or "法人"
        if cp in ("店舗", "店舗法人", "EC法人"):
            cp = "法人"
        idx = self.counterparty_combo.findText(cp)
        if idx < 0:
            self.counterparty_combo.addItem(cp)
            idx = self.counterparty_combo.findText(cp)
        self.counterparty_combo.setCurrentIndex(max(0, idx))

        self.notes_edit.setText(_as_str(r.get("notes")))
        self.counterparty_name_edit.setText(_as_str(r.get("counterparty_name")))
        self.counterparty_branch_edit.setText(_as_str(r.get("counterparty_branch")))
        self.counterparty_address_edit.setText(_as_str(r.get("counterparty_address")))
        self.contact_edit.setText(_as_str(r.get("contact")))
        self.receipt_no_edit.setText(_as_str(r.get("receipt_no")))
        self.platform_edit.setText(_as_str(r.get("platform")))
        self.platform_order_id_edit.setText(_as_str(r.get("platform_order_id")))
        self.platform_user_edit.setText(_as_str(r.get("platform_user")))
        self.person_name_edit.setText(_as_str(r.get("person_name")))
        self.person_address_edit.setText(_as_str(r.get("person_address")))
        self.id_type_edit.setText(_as_str(r.get("id_type")))
        self.id_number_edit.setText(_as_str(r.get("id_number")))
        self.id_checked_on_edit.setText(_as_str(r.get("id_checked_on")))
        self.id_checked_by_edit.setText(_as_str(r.get("id_checked_by")))
        self.id_proof_ref_edit.setText(_as_str(r.get("id_proof_ref")))

    def _recalc_amount(self, *_args: Any) -> None:
        self.amount_spin.setValue(self.qty_spin.value() * self.unit_price_spin.value())

    def _open_receipt_url(self) -> None:
        url = self.receipt_no_edit.text().strip()
        if not url:
            QMessageBox.information(self, "URLを開く", "レシート画像URLが空です。")
            return
        if not (url.startswith("http://") or url.startswith("https://")):
            QMessageBox.warning(
                self, "URLを開く", "http:// または https:// で始まるURLを入力してください。"
            )
            return
        qurl = QUrl(url)
        if not qurl.isValid():
            QMessageBox.warning(self, "URLを開く", "URLの形式が正しくありません。")
            return
        QDesktopServices.openUrl(qurl)

    def get_values(self) -> Dict[str, Any]:
        """保存用の辞書を返す。"""
        kind = self.kobutsu_combo.currentText().strip()
        return {
            "entry_date": self.entry_date_edit.date().toString("yyyy-MM-dd"),
            "kobutsu_kind": kind,
            "hinmoku": kind,
            "hinmei": self.hinmei_edit.text().strip(),
            "transaction_method": self.transaction_method_edit.text().strip() or "買受",
            "qty": int(self.qty_spin.value()),
            "unit_price": int(self.unit_price_spin.value()),
            "amount": int(self.amount_spin.value()),
            "identifier": self.identifier_edit.text().strip(),
            "sku": self.sku_edit.text().strip(),
            "counterparty_type": self.counterparty_combo.currentText().strip(),
            "notes": self.notes_edit.text().strip(),
            "counterparty_name": self.counterparty_name_edit.text().strip(),
            "counterparty_branch": self.counterparty_branch_edit.text().strip(),
            "counterparty_address": self.counterparty_address_edit.text().strip(),
            "contact": self.contact_edit.text().strip(),
            "receipt_no": self.receipt_no_edit.text().strip(),
            "platform": self.platform_edit.text().strip(),
            "platform_order_id": self.platform_order_id_edit.text().strip(),
            "platform_user": self.platform_user_edit.text().strip(),
            "person_name": self.person_name_edit.text().strip(),
            "person_address": self.person_address_edit.text().strip(),
            "id_type": self.id_type_edit.text().strip(),
            "id_number": self.id_number_edit.text().strip(),
            "id_checked_on": self.id_checked_on_edit.text().strip(),
            "id_checked_by": self.id_checked_by_edit.text().strip(),
            "id_proof_ref": self.id_proof_ref_edit.text().strip(),
        }

    def _on_accept(self) -> None:
        values = self.get_values()
        if not values.get("hinmei"):
            QMessageBox.warning(self, "入力チェック", "品名は必須です。")
            return
        if not values.get("kobutsu_kind"):
            QMessageBox.warning(self, "入力チェック", "品目を選択（または入力）してください。")
            return
        self.accept()

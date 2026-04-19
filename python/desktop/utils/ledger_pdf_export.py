#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
古物台帳 PDF 出力（ReportLab・OS 標準の日本語 TrueType フォントを利用）
"""
from __future__ import annotations

import copy
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


_JP_FONT_NAME = "LedgerJP"
_JP_FONT_REGISTERED = False

# 明細テーブル列幅の相対重み（大きいほど横に広い）。特に「品名」に幅を割り当てる。
_LEDGER_COL_WEIGHT: Dict[str, float] = {
    "品名": 4.0,
    "店舗住所": 2.6,
    "個人住所": 2.6,
    "出品URL": 2.0,
    "仕入先名": 1.9,
    "備考": 1.45,
    "証憑参照": 1.5,
    "取引日": 1.05,
    "品目": 1.0,
    # JAN 等 13 桁が 1 行に収まるようやや広め（短い列から幅を再配分）
    "識別情報": 1.38,
    "SKU": 1.15,
    "相手区分": 0.82,
    "取引方法": 0.95,
    "数量": 0.55,
    "単価": 0.78,
    "金額": 0.78,
    "支店": 1.05,
    "連絡先": 1.15,
    "プラットフォーム": 1.05,
    "取引ID": 1.05,
    "ユーザー名": 1.1,
    "伝票番号": 1.05,
    "受取都道府県": 0.95,
    "氏名": 1.25,
    "生年月日": 0.9,
    "本人確認種別": 1.0,
    "番号": 0.9,
    "確認日": 0.9,
    "確認者": 0.9,
}
_DEFAULT_COL_WEIGHT = 1.0


class LedgerPageNumberCanvas(rl_canvas.Canvas):
    """
    Platypus 組版中はページを確定せず状態だけ蓄え、save() でまとめて PDF 化する。
    各ページ右下に「◯ページ / 全◯ページ」（ReportLab ユーザーズ向け定番パターン）。
    ※ SimpleDocTemplate は doc.build(..., canvasmaker=...) を指定しないと
    デフォルト Canvas になり、このクラスが使われない。
    """

    def __init__(self, *args: Any, footer_font_name: str = _JP_FONT_NAME, **kwargs: Any) -> None:
        self._footer_font_name = footer_font_name
        self._page_states: List[dict] = []
        rl_canvas.Canvas.__init__(self, *args, **kwargs)

    def showPage(self) -> None:
        # 現在ページの描画命令を保持し、_startPage で次ページ用にリセット（親の showPage は呼ばない）
        try:
            self._page_states.append(copy.deepcopy(dict(self.__dict__)))
        except Exception:
            self._page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        if not self._page_states:
            rl_canvas.Canvas.save(self)
            return
        total = len(self._page_states)
        for idx, state in enumerate(self._page_states, start=1):
            self.__dict__.update(state)
            self._draw_page_footer(idx, total)
            rl_canvas.Canvas.showPage(self)
        rl_canvas.Canvas.save(self)

    def _draw_page_footer(self, page_no: int, total: int) -> None:
        self.saveState()
        try:
            self.setFont(self._footer_font_name, 9)
        except Exception:
            self.setFont("Helvetica", 9)
        w, _h = self._pagesize
        margin_x = 24
        margin_y = 16
        text = f"{page_no}ページ / 全{total}ページ"
        self.setFillColor(colors.black)
        self.drawRightString(w - margin_x, margin_y, text)
        self.restoreState()


def find_japanese_ttf_path() -> Optional[str]:
    """日本語表示用の .ttf を探索（Windows の優先）。"""
    candidates: List[Path] = []
    windir = os.environ.get("WINDIR")
    if windir:
        fd = Path(windir) / "Fonts"
        # 可変フォント（-VF）は PDF 上で線が細く見えやすいため、後回しにする
        candidates.extend(
            [
                fd / "YuGothic-Medium.ttf",
                fd / "YuGothicUI-Medium.ttf",
                fd / "meiryob.ttf",
                fd / "YuGothicUI-Regular.ttf",
                fd / "YuGothic-Regular.ttf",
                fd / "meiryo.ttf",
                fd / "msgothic.ttf",
                fd / "msmincho.ttf",
                fd / "yumin.ttf",
                fd / "NotoSansJP-VF.ttf",
                fd / "NotoSerifJP-VF.ttf",
            ]
        )
    for p in (
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttf"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttf"),
    ):
        candidates.append(p)
    for p in candidates:
        if p.is_file() and p.suffix.lower() == ".ttf":
            return str(p)
    return None


def _ensure_japanese_font() -> str:
    global _JP_FONT_REGISTERED
    if _JP_FONT_REGISTERED:
        return _JP_FONT_NAME
    path = find_japanese_ttf_path()
    if not path:
        raise RuntimeError(
            "日本語PDF用のTrueTypeフォント（.ttf）が見つかりません。"
            "Windowsでは Yu Gothic / Meiryo などが通常利用できます。"
        )
    pdfmetrics.registerFont(TTFont(_JP_FONT_NAME, path))
    _JP_FONT_REGISTERED = True
    return _JP_FONT_NAME


def _truncate_cell(text: str, max_len: int = 48) -> str:
    s = str(text) if text is not None else ""
    s = s.replace("\r\n", " ").replace("\n", " ").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def _cell_value(val: Any) -> str:
    """DataFrame 由来の nan などを空文字に。"""
    if val is None:
        return ""
    try:
        if isinstance(val, float) and math.isnan(val):
            return ""
    except (TypeError, ValueError):
        pass
    return _truncate_cell(str(val))


def _scalar_to_str(val: Any) -> str:
    """PDFセル用（折り返しのため全文・改行は <br/> に変換前に保持）。"""
    if val is None:
        return ""
    try:
        if isinstance(val, float) and math.isnan(val):
            return ""
    except (TypeError, ValueError):
        pass
    return str(val)


def _paragraph_xml_content(raw: str) -> str:
    """ReportLab Paragraph 用に XML エスケープし、改行を <br/> に。"""
    t = raw.replace("\r\n", "\n").replace("\r", "\n")
    parts = t.split("\n")
    return "<br/>".join(escape(p) for p in parts)


def _ledger_detail_col_widths(headers: Sequence[str], usable_pt: float) -> List[float]:
    """固定列幅（pt）。品名など重みの大きい列ほど広い。"""
    if not headers:
        return []
    weights = [_LEDGER_COL_WEIGHT.get(h, _DEFAULT_COL_WEIGHT) for h in headers]
    s = sum(weights) or 1.0
    return [usable_pt * w / s for w in weights]


def write_ledger_pdf(
    target: Path,
    cover_pairs: Sequence[Tuple[str, str]],
    sections: Sequence[Tuple[str, List[Dict[str, Any]]]],
    column_headers: Sequence[str],
) -> None:
    """
    :param cover_pairs: 表紙の (項目, 内容) 行（ヘッダー行は含めない）
    :param sections: (月見出し, 行データの辞書リスト) ※辞書のキーは column_headers と一致
    :param column_headers: 明細表の列見出し（日本語）
    """
    font = _ensure_japanese_font()
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        name="LedgerTitle",
        parent=styles["Heading1"],
        fontName=font,
        fontSize=16,
        textColor=colors.black,
        alignment=TA_CENTER,
        spaceAfter=12,
    )
    h2_style = ParagraphStyle(
        name="LedgerH2",
        parent=styles["Heading2"],
        fontName=font,
        fontSize=11,
        textColor=colors.black,
        spaceAfter=6,
        spaceBefore=6,
    )
    body_style = ParagraphStyle(
        name="LedgerBody",
        parent=styles["Normal"],
        fontName=font,
        fontSize=9,
        textColor=colors.black,
    )
    # 明細セル: Paragraph で折り返し・行高は内容に応じ自動（小さすぎると印刷で薄く掠れやすい）
    hdr_cell_style = ParagraphStyle(
        name="LedgerTblHdr",
        fontName=font,
        fontSize=6.5,
        leading=8.0,
        textColor=colors.black,
        alignment=TA_CENTER,
        spaceBefore=0,
        spaceAfter=0,
    )
    body_cell_style = ParagraphStyle(
        name="LedgerTblCell",
        fontName=font,
        fontSize=6.0,
        leading=7.5,
        textColor=colors.black,
        alignment=TA_LEFT,
        spaceBefore=0,
        spaceAfter=0,
        wordWrap="CJK",
    )

    page_size = landscape(A4)
    doc = SimpleDocTemplate(
        str(target),
        pagesize=page_size,
        leftMargin=24,
        rightMargin=24,
        topMargin=28,
        bottomMargin=36,
    )

    def _ledger_canvas_maker(*args: Any, **kwargs: Any) -> LedgerPageNumberCanvas:
        return LedgerPageNumberCanvas(*args, footer_font_name=font, **kwargs)
    story: List[Any] = []

    # ----- 表紙 -----
    story.append(Paragraph("古物台帳（表紙）", title_style))
    story.append(Spacer(1, 6 * mm))
    cover_data: List[List[str]] = [["項目", "内容"]]
    for a, b in cover_pairs:
        cover_data.append([str(a), str(b)])
    cw = (page_size[0] - 48) / 2
    cover_tbl = Table(cover_data, colWidths=[cw, cw], repeatRows=1)
    cover_tbl.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, -1), font, 9),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d4e8d4")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#666666")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(cover_tbl)
    story.append(PageBreak())

    # ----- 明細（月別） -----
    headers = list(column_headers)
    usable_w_pt = page_size[0] - doc.leftMargin - doc.rightMargin
    col_widths = _ledger_detail_col_widths(headers, usable_w_pt)

    for sec_idx, (month_title, row_dicts) in enumerate(sections):
        story.append(Paragraph(str(month_title), h2_style))
        tbl_data: List[List[Any]] = []
        hdr_row = [Paragraph(_paragraph_xml_content(h), hdr_cell_style) for h in headers]
        tbl_data.append(hdr_row)
        for rd in row_dicts:
            row_cells = [
                Paragraph(_paragraph_xml_content(_scalar_to_str(rd.get(h, ""))), body_cell_style)
                for h in headers
            ]
            tbl_data.append(row_cells)
        if len(tbl_data) == 1:
            story.append(Paragraph("（明細なし）", body_style))
        else:
            t = Table(
                tbl_data,
                colWidths=col_widths,
                repeatRows=1,
            )
            t.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d4e8d4")),
                        ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
                        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#666666")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 2),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                        ("TOPPADDING", (0, 0), (-1, -1), 2),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                    ]
                )
            )
            story.append(t)
        if sec_idx < len(sections) - 1:
            story.append(PageBreak())

    # canvasmaker は build() に渡す必要がある（__init__ だけでは Platypus が無視する）
    doc.build(story, canvasmaker=_ledger_canvas_maker)

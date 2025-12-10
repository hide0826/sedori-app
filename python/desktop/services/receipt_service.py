#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
レシートサービス

- 画像保存（所定ディレクトリ）
- OCR実行（OCRService）
- 金額/税/クーポン/支払額などを抽出
- ReceiptDatabase に保存
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from ..database.receipt_db import ReceiptDatabase
from ..services.gemini_receipt_service import GeminiReceiptService
from ..services.ocr_service import OCRService


@dataclass
class ReceiptParseResult:
    purchase_date: Optional[str]
    purchase_time: Optional[str]  # HH:MM形式
    store_name_raw: Optional[str]
    phone_number: Optional[str]
    subtotal: Optional[int]
    tax: Optional[int]
    discount_amount: Optional[int]
    total_amount: Optional[int]
    paid_amount: Optional[int]
    items_count: Optional[int]
    plastic_bag_amount: Optional[int]  # レジ袋金額（複数ある場合は合計）


logger = logging.getLogger(__name__)


class ReceiptService:
    def __init__(self, base_dir: Optional[str | Path] = None, tesseract_cmd: Optional[str] = None, gcv_credentials_path: Optional[str] = None, tessdata_dir: Optional[str] = None):
        self.base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parents[2] / "python" / "desktop" / "data" / "receipts"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.db = ReceiptDatabase()
        self.ocr = OCRService(tesseract_cmd=tesseract_cmd, gcv_credentials_path=gcv_credentials_path, tessdata_dir=tessdata_dir)
        try:
            self.ai_service = GeminiReceiptService()
        except Exception as exc:  # pragma: no cover - 外部依存
            logger.debug("GeminiReceiptService initialization failed: %s", exc)
            self.ai_service = None

    def save_image(self, src_path: str | Path) -> Path:
        src_path = Path(src_path)
        if not src_path.exists():
            raise FileNotFoundError(src_path)
        # ファイル名: receipt_YYYYmmdd_HHMMSS_uuid拡張子は元ファイルのまま
        import uuid, datetime, shutil
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        dst = self.base_dir / f"receipt_{stamp}_{uuid.uuid4().hex}{src_path.suffix.lower()}"
        shutil.copy2(src_path, dst)
        # 絶対パスを返す（リネーム処理で確実にファイルを見つけられるように）
        return dst.resolve()

    def parse_receipt_text(self, text: str) -> ReceiptParseResult:
        """OCRテキストからレシート情報を抽出（簡易版）"""
        # 日付抽出（複数形式に対応）
        purchase_date = None
        
        # パターン1: yyyy-mm-dd or yyyy/mm/dd or yyyy.mm.dd
        m_date = re.search(r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})", text)
        if m_date:
            y, mo, d = m_date.groups()
            # 仕入DBと揃えるため「yyyy/MM/dd」形式に統一
            purchase_date = f"{int(y):04d}/{int(mo):02d}/{int(d):02d}"
        
        # パターン2: yyyy年mm月dd日 or yyyy年mm月dd
        if not purchase_date:
            m_date = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日?", text)
            if m_date:
                y, mo, d = m_date.groups()
                purchase_date = f"{int(y):04d}/{int(mo):02d}/{int(d):02d}"
        
        # パターン3: 令和X年mm月dd日 (令和7年 = 2025年)
        if not purchase_date:
            m_date = re.search(r"令和(\d{1,2})年(\d{1,2})月(\d{1,2})日?", text)
            if m_date:
                reiwa_year, mo, d = m_date.groups()
                # 令和年を西暦に変換（令和1年 = 2019年）
                y = 2018 + int(reiwa_year)
                purchase_date = f"{y:04d}/{int(mo):02d}/{int(d):02d}"
        
        # パターン4: R7年mm月dd日 (R7年 = 2025年)
        if not purchase_date:
            m_date = re.search(r"R(\d{1,2})年(\d{1,2})月(\d{1,2})日?", text)
            if m_date:
                reiwa_year, mo, d = m_date.groups()
                # 令和年を西暦に変換（令和1年 = 2019年）
                y = 2018 + int(reiwa_year)
                purchase_date = f"{y:04d}/{int(mo):02d}/{int(d):02d}"

        # 時刻抽出（日付の近くを優先的に検索）
        purchase_time = None
        if purchase_date:
            # 日付が見つかった行の近くを検索
            lines = text.splitlines()
            date_line_idx = None
            # 数字だけ取り出して比較（区切り文字の違いを吸収）
            def _digits_only(s: str) -> str:
                return re.sub(r"\D", "", s)
            for i, line in enumerate(lines):
                if _digits_only(purchase_date)[:8] in _digits_only(line):
                    date_line_idx = i
                    break
            
            # 日付の行とその前後3行を検索範囲とする
            search_lines = []
            if date_line_idx is not None:
                start_idx = max(0, date_line_idx - 3)
                end_idx = min(len(lines), date_line_idx + 4)
                search_lines = lines[start_idx:end_idx]
            else:
                # 日付が見つからない場合は全体を検索
                search_lines = lines
            
            # 時刻パターン1: HH:MM形式（例: 14:30）
            for line in search_lines:
                m_time = re.search(r"(\d{1,2}):(\d{2})(?::\d{2})?", line)
                if m_time:
                    h, m = m_time.groups()[:2]
                    try:
                        hour = int(h)
                        minute = int(m)
                        if 0 <= hour <= 23 and 0 <= minute <= 59:
                            purchase_time = f"{hour:02d}:{minute:02d}"
                            break
                    except ValueError:
                        continue
            
            # 時刻パターン2: HH時MM分形式（例: 14時30分）
            if not purchase_time:
                for line in search_lines:
                    m_time = re.search(r"(\d{1,2})時(\d{1,2})分", line)
                    if m_time:
                        h, m = m_time.groups()
                        try:
                            hour = int(h)
                            minute = int(m)
                            if 0 <= hour <= 23 and 0 <= minute <= 59:
                                purchase_time = f"{hour:02d}:{minute:02d}"
                                break
                        except ValueError:
                            continue
            
            # 時刻パターン3: HHMM形式（例: 1430）
            if not purchase_time:
                for line in search_lines:
                    m_time = re.search(r"(\d{1,2})(\d{2})(?!\d)", line)
                    if m_time:
                        h, m = m_time.groups()
                        try:
                            hour = int(h)
                            minute = int(m)
                            # 4桁の数字で、時刻として妥当な範囲かチェック
                            if 0 <= hour <= 23 and 0 <= minute <= 59:
                                # 前後の文字をチェック（商品コードなどと区別）
                                match_start = m_time.start()
                                match_end = m_time.end()
                                # 前後に時刻を示すキーワードがあるか、または単独で存在するか
                                context = line[max(0, match_start-5):min(len(line), match_end+5)]
                                if any(keyword in context for keyword in ["時", "分", ":", "時刻", "時間"]) or \
                                   (match_start == 0 or not line[match_start-1].isdigit()) and \
                                   (match_end >= len(line) or not line[match_end].isdigit()):
                                    purchase_time = f"{hour:02d}:{minute:02d}"
                                    break
                        except ValueError:
                            continue
        
        # 店舗名の抽出（新規実装）
        # レシートの一般的な構造を考慮して店舗名を抽出
        lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
        import unicodedata
        normalized_lines = [unicodedata.normalize('NFKC', line) for line in lines]
        store_name_raw = None
        
        # スキップする一般的なレシートヘッダー
        skip_patterns = [
            "領収書", "お買上げ明細", "お買い上げ明細", "レシート", "receipt",
            "合計", "小計", "税", "お預り", "お預かり", "支払",
            "商品名", "金額", "商品", "明細", "内訳"
        ]
        
        # 電話番号の位置を特定
        phone_line_idx = None
        for i, line in enumerate(lines):
            if re.search(r"\d{2,4}[-−‐ー―]?\d{2,4}[-−‐ー―]?\d{3,4}", line):
                phone_line_idx = i
                break
        
        # 店舗名の候補を探す（優先度付き）
        candidates = []
        for i, line in enumerate(lines):
            # スキップパターンに該当する行は除外
            if any(pattern in line for pattern in skip_patterns):
                continue
            
            # 数字のみ、記号のみ、住所らしい行は除外
            if re.match(r"^[\d\s,\.]+$", line):
                continue
            if re.match(r"^[*★☆\-=]+$", line):
                continue
            if re.search(r"[都道府県市区町村]", line):
                continue
            
            # 優先度を計算
            priority = 0
            
            # 電話番号の近く（前後3行以内）を優先
            if phone_line_idx is not None:
                distance = abs(i - phone_line_idx)
                if distance <= 3:
                    priority += (10 - distance) * 2  # 近いほど優先度が高い
            
            # 店舗名らしいキーワードを含む行を優先
            if re.search(r"(店|ショップ|ストア|マート|センター|ファクトリー|フリー|マーケット)", line):
                priority += 20
            
            # 長い行（店舗名の可能性が高い）を優先
            if len(line) >= 5:
                priority += 5
            
            # 店舗名らしい文字列（カタカナ、漢字、英字を含む）を優先
            if re.search(r"[ァ-ヶ一-龠A-Za-z]", line):
                priority += 3
            
            if priority > 0:
                candidates.append((priority, i, line))
        
        # 優先度順にソートして最上位を選択
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            store_name_raw = candidates[0][2][:64]  # 最大64文字
        else:
            # 候補が見つからない場合は、電話番号の前の行を試す
            if phone_line_idx is not None and phone_line_idx > 0:
                for i in range(phone_line_idx - 1, max(0, phone_line_idx - 4), -1):
                    line = lines[i]
                    if any(pattern in line for pattern in skip_patterns):
                        continue
                    if re.match(r"^[\d\s,\.]+$", line):
                        continue
                    if re.search(r"[都道府県市区町村]", line):
                        continue
                    if len(line) >= 3:
                        store_name_raw = line[:64]
                        break
        
        # SSで始まる店舗名を「セカンドストリート」に変換
        if store_name_raw and store_name_raw.startswith('SS'):
            store_name_raw = 'セカンドストリート' + store_name_raw[2:]

        # 金額類（日本語表記の代表パターン）
        def _find_int(patterns: list[str]) -> Optional[int]:
            for pat in patterns:
                m = re.search(pat, text, flags=re.IGNORECASE)
                if m:
                    val = _to_int(m.group(1))
                    if val is not None:
                        return val
            return None

        def _to_int(s: str | None) -> Optional[int]:
            if not s:
                return None
            # カンマ・空白・ドットを除去、全角→半角
            # レシートでは「5, 291」「5.291」のような揺れがあるため、
            # ドットも桁区切りとして扱い、単純に削除する
            import unicodedata
            s = unicodedata.normalize('NFKC', s)
            # 数値以外の通貨記号などを除去
            for ch in [',', ' ', '\t', '.', '¥', '￥']:
                s = s.replace(ch, '')
            # 末尾のマイナスや括弧は無視（例: "5291-" "(5291)"）
            s = s.strip()
            if s.endswith('-'):
                s = s[:-1]
            if s.startswith('(') and s.endswith(')') and len(s) > 2:
                s = s[1:-1]
            if not s or not re.search(r'\d', s):
                return None
            try:
                return int(s)
            except Exception:
                return None

        # 数値部分は「5,291」「5, 291」のようにカンマ後に半角スペースが入るケースがあるため
        # 空白も許容するパターンにしている（[0-9,\. \t]+）
        subtotal = _find_int([r"小計\s*[:：]?\s*([0-9,\. \t]+)", r"税抜\s*[:：]?\s*([0-9,\. \t]+)"])  # 税抜/小計
        tax = _find_int([r"税\s*[:：]?\s*([0-9,\. \t]+)", r"消費税\s*[:：]?\s*([0-9,\. \t]+)", r"内税\s*[:：]?\s*\(?10%\)?\s*[:：]?\s*([0-9,\. \t]+)"])
        discount_amount = _find_int([r"値引[き|き額]?\s*[:：-]?\s*([0-9,\. \t]+)", r"クーポン\s*[:：-]?\s*([0-9,\. \t]+)"])
        paid_amount = _find_int([
            r"お預り\s*[:：]?\s*([0-9,\.]+)",
            r"お預かり\s*[:：]?\s*([0-9,\.]+)",
            r"支払\s*[:：]?\s*([0-9,\.]+)",
            r"支払い\s*[:：]?\s*([0-9,\.]+)",
            r"クレジットカード預り額\s*[:：]?\s*([0-9,\.]+)",
            r"クレジット\s*[:：]?\s*([0-9,\.]+)"
        ])
        # 合計の抽出を強化（「合計」や「クレジット決済」キーワードの後の金額を優先）
        # 「合計 total」→改行→「¥5, 291」のように行が分かれていてもマッチするように、
        # キーワードの後は「数字が出てくるまでの任意文字＋任意の¥記号」を許容する
        raw_total_amount = None
        total_patterns = [
            r"合計\s+total\s*[:：]?[^\d¥\-]*¥?\s*([0-9,\. \t]+)",  # 合計 total -> 5,291
            r"合計\s*[:：]?[^\d¥\-]*¥?\s*([0-9,\. \t]+)",         # 合計: 5,291 / 合計 ¥5,291
            r"合\s*計\s*[:：]?[^\d¥\-]*¥?\s*([0-9,\. \t]+)",      # 合 計: 5,291
            r"税込\s*[:：]?[^\d¥\-]*¥?\s*([0-9,\. \t]+)",         # 税込 5,291
            r"10%対象計\s*[:：]?[^\d¥\-]*¥?\s*([0-9,\. \t]+)",    # 10%対象計 5,291
            r"10%\s*対象計\s*[:：]?[^\d¥\-]*¥?\s*([0-9,\. \t]+)",  # 10% 対象計 5,291
            r"クレジット決済\s*[:：]?[^\d¥\-]*¥?\s*([0-9,\. \t]+)", # クレジット決済 5,291
            r"クレジットカード預り額\s*[:：]?[^\d¥\-]*¥?\s*([0-9,\. \t]+)",  # クレジットカード預り額 5,291
            r"クレジット\s*[:：]?[^\d¥\-]*¥?\s*([0-9,\. \t]+)",   # クレジット 5,291
        ]
        for pat in total_patterns:
            m = re.search(pat, text, flags=re.IGNORECASE)
            if m:
                val = _to_int(m.group(1))
                if val is not None and val >= 100:  # 100円未満は除外（点数などの誤検出防止）
                    raw_total_amount = val
                    break
        
        # 正規化されたテキストでも検索（OCRの誤認識に対応）
        if raw_total_amount is None:
            for pat in total_patterns:
                m = re.search(pat, '\n'.join(normalized_lines), flags=re.IGNORECASE)
                if m:
                    val = _to_int(m.group(1))
                    if val is not None and val >= 100:
                        raw_total_amount = val
                        break

        def _extract_amount_from_line(line: str) -> Optional[int]:
            """行から金額を抽出（キーワードの後の大きな数字を優先）"""
            # 店舗IDやレジ番号などの除外パターン
            exclude_patterns = [
                r"Store\s*ID", r"StoreID", r"店舗ID", r"店ID",
                r"レジ\s*[:：]?\s*\d+", r"レジNo", r"レジ番号",
                r"No\.\s*\d+", r"番号\s*\d+", r"会員番号",
                r"登録番号", r"Transaction\s*Number", r"取引番号",
                r"^\d{4,5}\s*$",  # 4桁または5桁の数字だけの行（店舗IDの可能性が高い）
            ]
            if any(re.search(pat, line, flags=re.IGNORECASE) for pat in exclude_patterns):
                return None
            
            # 商品価格行を除外（商品名を含む行は除外）
            product_keywords = [
                r"キッズ", r"日用品", r"玩具", r"生活用品", r"レジ袋",
                r"商品名", r"商品", r"品名", r"名称",
                r"^\s*[A-Za-z0-9]+\s+",  # 商品コードで始まる行
            ]
            # ただし、「合計」などのキーワードが含まれている場合は除外しない
            has_total_keyword = re.search(r"合計|税込|対象計|クレジット|支払", line, flags=re.IGNORECASE)
            if not has_total_keyword and any(re.search(pat, line, flags=re.IGNORECASE) for pat in product_keywords):
                return None
            
            # キーワードの後の金額を探す（例：「合計 4,405」）
            # キーワードマッチングが成功した場合のみ金額を返す
            keyword_patterns = [
                r"合計\s+total\s*[:：]?[^\d¥\-]*¥?\s*([0-9,\. \t]+)",  # 合計 total: 5,291
                r"合計\s*[:：]?[^\d¥\-]*¥?\s*([0-9,\. \t]+)",
                r"合\s*計\s*[:：]?[^\d¥\-]*¥?\s*([0-9,\. \t]+)",
                r"税込\s*[:：]?[^\d¥\-]*¥?\s*([0-9,\. \t]+)",
                r"10%対象計\s*[:：]?[^\d¥\-]*¥?\s*([0-9,\. \t]+)",  # 10%対象計: 4,405
                r"10%\s*対象計\s*[:：]?[^\d¥\-]*¥?\s*([0-9,\. \t]+)",  # 10% 対象計: 4,405
                r"対象計\s*[:：]?[^\d¥\-]*¥?\s*([0-9,\. \t]+)",
                r"クレジットカード預り額\s*[:：]?[^\d¥\-]*¥?\s*([0-9,\. \t]+)",  # クレジットカード預り額: 4,405
                r"クレジットカード\s*[:：]?[^\d¥\-]*¥?\s*([0-9,\. \t]+)",
                r"クレジット決済\s*[:：]?[^\d¥\-]*¥?\s*([0-9,\. \t]+)",  # クレジット決済: 5,291
                r"クレジット\s*[:：]?[^\d¥\-]*¥?\s*([0-9,\. \t]+)",
                r"支払\s*[:：]?[^\d¥\-]*¥?\s*([0-9,\. \t]+)",
            ]
            for pat in keyword_patterns:
                m = re.search(pat, line, flags=re.IGNORECASE)
                if m:
                    val = _to_int(m.group(1))
                    if val is not None and val >= 100:
                        return val
            
            # キーワードマッチングが失敗した場合は、金額を抽出しない
            # （商品価格や店舗IDなどの誤検出を防ぐため）
            return None

        def _determine_total_amount() -> Optional[int]:
            # 最終的に返す合計候補（途中でより大きな値が見つかったら更新）
            total_candidate: Optional[int] = raw_total_amount

            keyword_priorities = [
                (100, ["合計", "総合計", "合 計", "合計金額", "合　計", "合計 total"]),
                (95, ["10%対象計", "10%対象金額", "10%対象額", "10% 対象計"]),  # 税率行の合計も有効
                (90, ["税込合計", "税込金額", "税込計", "総計"]),
                (85, ["クレジットカード預り額", "カード預り額", "クレジットカード", "クレジット決済"]),  # 支払額も有効
                (80, ["対象計", "対象金額", "対象額"]),
                (70, ["お支払金額", "お支払い金額", "支払合計", "支払額", "クレジット"]),
                (60, ["預り額", "カード預り"]),
            ]
            # 除外キーワード（正規表現パターンに変更）
            exclude_patterns = [
                r"お釣り", r"釣銭", r"釣り銭", r"ポイント", r"pt残高", r"会員", r"残高", 
                r"有効期限", r"登録事業者", r"担当者", r"レジNo", r"レシートNo", r"レジ\s*:",
                r"Store\s*ID", r"StoreID", r"店舗ID", r"店ID", r"Transaction\s*Number",
                r"会\s*員\s*番\s*号", r"会\s*員\s*ポ\s*イ\s*ン\s*ト", r"発\s*行\s*ポ\s*イ\s*ン\s*ト"
            ]
            
            # 商品価格行を除外するキーワード
            product_keywords = [
                "キッズ", "日用品", "玩具", "生活用品", "レジ袋",
                "商品名", "商品", "品名", "名称"
            ]
            currency_tokens = ("¥", "円", "YEN", "yen", "￥", "込")
            candidates: list[tuple[int, int, int]] = []

            for idx, line in enumerate(normalized_lines):
                # 除外パターンを含む行はスキップ（正規表現でスペース揺らぎに対応）
                if any(re.search(pat, line, flags=re.IGNORECASE) for pat in exclude_patterns):
                    continue
                
                # 「10%」だけの行（税率表示）は除外
                if re.match(r"^10%", line.strip()) and len(line.strip()) < 20:
                    continue
                
                # 商品価格行を除外（商品名を含む行は除外）
                # ただし、「合計」などのキーワードが含まれている場合は除外しない
                has_total_keyword = re.search(r"合計|税込|対象計|クレジット|支払", line, flags=re.IGNORECASE)
                if not has_total_keyword and any(keyword in line for keyword in product_keywords):
                    continue
                
                amount = _extract_amount_from_line(line)
                if amount is None:
                    continue
                
                # 100円未満は除外（点数や税率などの誤検出防止）
                if amount < 100:
                    continue
                
                # 「点」を含む行で通貨記号がない場合は除外
                contains_currency = any(token in line for token in currency_tokens)
                if "点" in line and not contains_currency:
                    continue
                
                # キーワードマッチング
                for priority, keywords in keyword_priorities:
                    if any(keyword in line for keyword in keywords):
                        candidates.append((priority, -idx, amount))
                        break

            if candidates:
                candidates.sort(reverse=True)
                best_from_lines = candidates[0][2]
                if total_candidate is None or best_from_lines > total_candidate:
                    total_candidate = best_from_lines

            # フォールバック1：小計+税
            if subtotal is not None and tax is not None:
                calculated_total = subtotal + tax
                if calculated_total >= 100:  # 100円未満は除外
                    if total_candidate is None or calculated_total > total_candidate:
                        total_candidate = calculated_total

            # フォールバック2：支払額
            if paid_amount is not None and paid_amount >= 100:
                if total_candidate is None or paid_amount > total_candidate:
                    total_candidate = paid_amount

            # フォールバック3：行ごとに検索して最大の金額を返す（キーワードがマッチしない場合）
            # ただし、カンマ区切りの数字のみを抽出（金額は通常カンマ区切り、店舗IDはカンマなし）
            fallback_amounts = []
            store_id_patterns = [
                r"Store\s*ID", r"StoreID", r"店舗ID", r"店ID",
                r"レジ\s*[:：]?\s*\d+", r"レジNo", r"レジ番号",
                r"No\.\s*\d+", r"番号\s*\d+", r"会員番号",
                r"登録番号", r"Transaction\s*Number", r"取引番号",
                r"^\d{4,5}\s*$",  # 4桁または5桁の数字だけの行（店舗IDの可能性が高い）
            ]
            for line in normalized_lines:
                # 除外パターンを含む行はスキップ
                if any(re.search(pat, line, flags=re.IGNORECASE) for pat in exclude_patterns):
                    continue
                # 店舗IDやレジ番号を含む行はスキップ
                if any(re.search(pat, line, flags=re.IGNORECASE) for pat in store_id_patterns):
                    continue
                # 「10%」だけの短い行は除外
                if re.match(r"^10%", line.strip()) and len(line.strip()) < 20:
                    continue
                # 商品価格行を除外（商品名を含む行は除外）
                has_total_keyword = re.search(r"合計|税込|対象計|クレジット|支払", line, flags=re.IGNORECASE)
                if not has_total_keyword and any(keyword in line for keyword in product_keywords):
                    continue
                # カンマ区切りの数字のみを抽出（金額は通常カンマ区切り）
                comma_matches = re.findall(r"([0-9]{1,3}(?:,[0-9]{3})+)", line)
                for match in comma_matches:
                    val = _to_int(match)
                    if val is not None and val >= 100:  # 100円以上
                        fallback_amounts.append(val)
            
            if fallback_amounts:
                # 最も頻繁に出現する金額を返す（合計は通常複数回出現する）
                from collections import Counter
                counter = Counter(fallback_amounts)
                most_common = counter.most_common(1)
                if most_common:
                    max_fallback = most_common[0][0]
                    if total_candidate is None or max_fallback > total_candidate:
                        total_candidate = max_fallback

            return total_candidate

        total_amount = _determine_total_amount()

        # 電話番号
        def _normalize_phone(raw: str | None) -> Optional[str]:
            if not raw:
                return None
            import unicodedata

            s = unicodedata.normalize('NFKC', raw)
            s = s.replace('ー', '-').replace('−', '-').replace('―', '-').replace('‐', '-')
            s = re.sub(r"[^0-9-]", "", s)
            # 連続した数字のみの場合は標準的なハイフン位置に整形
            if '-' not in s and len(s) in (10, 11):
                if len(s) == 10:
                    s = f"{s[0:2]}-{s[2:6]}-{s[6:]}"
                else:
                    s = f"{s[0:3]}-{s[3:7]}-{s[7:]}"
            parts = [p for p in s.split('-') if p]
            if len(parts) >= 3:
                return "-".join(parts[:3])
            return s or None

        phone_number = None
        phone_patterns = [
            r"(?:TEL|Tel|tel|電話|☎|ＴＥＬ)\s*[:：]?\s*(\d{2,4}[-−‐ー―]?\d{2,4}[-−‐ー―]?\d{3,4})",
            r"(\d{2,4}[-−‐ー―]?\d{2,4}[-−‐ー―]?\d{3,4})"
        ]
        for pat in phone_patterns:
            m = re.search(pat, text)
            if m:
                phone_number = _normalize_phone(m.group(1))
                if phone_number:
                    break

        # 商品点数（削除：不要になったため）
        items_count = None

        # レジ袋金額の抽出（複数ある場合は合計）
        plastic_bag_amount = None
        plastic_bag_patterns = [
            r"レジ袋\s*[:：]?\s*([0-9,\. \t]+)",
            r"有料レジ袋\s*[:：]?\s*([0-9,\. \t]+)",
            r"レジ袋代\s*[:：]?\s*([0-9,\. \t]+)",
            r"袋代\s*[:：]?\s*([0-9,\. \t]+)",
            r"レジ袋\s+([0-9,\. \t]+)",  # レジ袋 5 のような形式
            r"有料レジ袋\s+([0-9,\. \t]+)",  # 有料レジ袋 5 のような形式
        ]
        plastic_bag_amounts = []
        for pat in plastic_bag_patterns:
            matches = re.finditer(pat, text, flags=re.IGNORECASE)
            for m in matches:
                val = _to_int(m.group(1))
                if val is not None and val > 0:  # 0より大きい値のみ
                    plastic_bag_amounts.append(val)
        
        # 複数のレジ袋がある場合は合計
        if plastic_bag_amounts:
            plastic_bag_amount = sum(plastic_bag_amounts)

        return ReceiptParseResult(
            purchase_date=purchase_date,
            purchase_time=purchase_time,
            store_name_raw=store_name_raw,
            phone_number=phone_number,
            subtotal=subtotal,
            tax=tax,
            discount_amount=discount_amount,
            total_amount=total_amount,
            paid_amount=paid_amount,
            items_count=None,  # 点数は削除
            plastic_bag_amount=plastic_bag_amount,
        )

    def process_receipt(self, image_path: str | Path, currency: str = "JPY") -> Dict[str, Any]:
        """
        レシート画像を保存→OCR→抽出→DB保存まで行い、保存結果を返す
        """
        # 元のファイルパスを保存（リネーム用）
        original_path = Path(image_path).resolve() if image_path else None
        saved = self.save_image(image_path)
        parsed: Optional[ReceiptParseResult] = None
        raw_text = ""
        ocr_provider = None

        # Gemini AIによる解析を優先（設定済みの場合）
        if self.ai_service and self.ai_service.is_available():
            try:
                ai_result = self.ai_service.extract_structured_data(saved)
                if ai_result:
                    parsed = ReceiptParseResult(
                        purchase_date=ai_result.get("purchase_date"),
                        purchase_time=ai_result.get("purchase_time"),
                        store_name_raw=ai_result.get("store_name_raw"),
                        phone_number=ai_result.get("phone_number"),
                        subtotal=ai_result.get("subtotal"),
                        tax=ai_result.get("tax"),
                        discount_amount=ai_result.get("discount_amount"),
                        total_amount=ai_result.get("total_amount"),
                        paid_amount=ai_result.get("paid_amount"),
                        items_count=ai_result.get("items_count"),
                        plastic_bag_amount=ai_result.get("plastic_bag_amount"),
                    )
                    raw_text = ai_result.get("raw_text") or ""
                    ocr_provider = ai_result.get("provider") or "gemini"
            except Exception as exc:  # pragma: no cover - 外部依存
                logger.warning("Gemini receipt parsing failed, falling back to OCR: %s", exc)
                parsed = None

        if parsed is None:
            ocr = self.ocr.extract_text(saved, use_preprocessing=True)
            raw_text = ocr.get("text") or ""
            parsed = self.parse_receipt_text(raw_text)
            ocr_provider = ocr.get("provider")

        # デバッグ用ログ: OCRテキストと抽出結果を記録（原因調査用）
        try:
            log_path = Path(__file__).resolve().parents[2] / "python" / "desktop" / "desktop_error.log"
            with open(log_path, "a", encoding="utf-8") as f:
                from datetime import datetime

                f.write("\n\n==== ReceiptService.process_receipt Debug ====\n")
                f.write(f"timestamp   : {datetime.now().isoformat(timespec='seconds')}\n")
                f.write(f"image_path  : {saved}\n")
                f.write(f"purchase_date: {parsed.purchase_date}\n")
                f.write(f"purchase_time: {parsed.purchase_time}\n")
                f.write(f"store_name  : {parsed.store_name_raw}\n")
                f.write(f"subtotal    : {parsed.subtotal}\n")
                f.write(f"tax         : {parsed.tax}\n")
                f.write(f"discount    : {parsed.discount_amount}\n")
                f.write(f"total_amount: {parsed.total_amount}\n")
                f.write(f"paid_amount : {parsed.paid_amount}\n")
                f.write(f"items_count : {parsed.items_count}\n")
                f.write("---- OCR text ----\n")
                f.write(raw_text)
                f.write("\n==== End Debug ====\n")
        except Exception:
            # ログ出力に失敗しても本処理には影響させない
            pass

        receipt_data = {
            "file_path": str(saved),
            "original_file_path": str(original_path) if original_path else None,  # 元のファイルパス
            "purchase_date": parsed.purchase_date,
            "purchase_time": parsed.purchase_time,  # 購入時刻（HH:MM形式）
            "store_name_raw": parsed.store_name_raw,
            "phone_number": parsed.phone_number,
            "store_code": None,  # マッチング段階で確定
            "subtotal": parsed.subtotal,
            "tax": parsed.tax,
            "discount_amount": parsed.discount_amount,
            "total_amount": parsed.total_amount,
            "paid_amount": parsed.paid_amount,
            "items_count": parsed.items_count,
            "plastic_bag_amount": parsed.plastic_bag_amount,
            "currency": currency,
            "ocr_provider": ocr_provider,
            "ocr_text": raw_text,
        }
        receipt_id = self.db.insert_receipt(receipt_data)
        receipt_data["id"] = receipt_id
        
        # ファイル名を新しい形式にリネーム: receipt_{YYYYMMDD}_{store_code}_{receipt_id}.{拡張子}
        try:
            # 日付をYYYYMMDD形式に変換（区切り文字はすべて除去）
            if parsed.purchase_date:
                import re as _re
                date_str = _re.sub(r"[^0-9]", "", parsed.purchase_date)
                if len(date_str) != 8:
                    date_str = "UNKNOWN"
            else:
                date_str = "UNKNOWN"
            
            # 店舗コード（未確定時はUNKNOWN）
            store_code = receipt_data.get("store_code") or "UNKNOWN"
            
            # 新しいファイル名を生成: {YYYYMMDD}_{store_code}_{receipt_id}.{拡張子}
            new_name = f"{date_str}_{store_code}_{receipt_id}{saved.suffix}"
            new_path = saved.parent / new_name
            
            # ファイルをリネーム
            if saved != new_path and saved.exists():
                saved.rename(new_path)
                # DBのfile_pathを更新
                self.db.update_receipt(receipt_id, {"file_path": str(new_path)})
                receipt_data["file_path"] = str(new_path)
        except Exception as e:
            # リネーム失敗時はログ出力して続行（元のパスを使用）
            try:
                log_path = Path(__file__).resolve().parents[2] / "python" / "desktop" / "desktop_error.log"
                with open(log_path, "a", encoding="utf-8") as f:
                    from datetime import datetime
                    f.write(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ReceiptService: Failed to rename receipt image: {e}\n")
            except Exception:
                pass
        
        return receipt_data

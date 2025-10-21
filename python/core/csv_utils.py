import pandas as pd
from io import BytesIO
from fastapi import HTTPException
import unicodedata
import re

def read_csv_with_fallback(content: bytes) -> pd.DataFrame:
    """
    Reads CSV content with multiple encoding fallbacks.
    Tries cp932, then utf-8, then latin1.
    """
    encodings = ["cp932", "utf-8", "latin1"]

    for encoding in encodings:
        try:
            # on_bad_lines='warn' は問題を警告しつつも処理を継続させる
            df = pd.read_csv(BytesIO(content), encoding=encoding, dtype=str, on_bad_lines='warn')
            return df
        except (UnicodeDecodeError, pd.errors.ParserError) as e:
            continue

    raise HTTPException(
        status_code=400,
        detail="Failed to decode CSV with cp932, utf-8, and latin1 encodings."
    )

def normalize_string_for_cp932(s: str) -> str:
    """
    Shift_JIS (cp932) で安全に出力できるように文字列を正規化
    1. NFKC正規化
    2. Shift_JISで変換できない文字を除去/置換
    3. 改行・タブを空白に置換
    """
    if not isinstance(s, str):
        return str(s) if s is not None else ""

    # 元の文字列を保存（デバッグ用）
    original = s

    # NFKC正規化（全角→半角、合字展開など）
    s = unicodedata.normalize('NFKC', s)

    # 【強化版】危険な記号を安全な文字に置換
    # GPT決定版の置換ルールを完全実装
    replacements = {
        # ダッシュ系（最優先で処理）
        '—': '-',  # emダッシュ
        '–': '-',  # enダッシュ
        '―': '-',  # ホリゾンタルバー
        '‐': '-',  # ハイフン
        '−': '-',  # マイナス記号
        'ー': '-',  # 全角長音（カタカナ）→半角ハイフンに統一

        # クォート系
        ''': "'",  # 左シングルクォート
        ''': "'",  # 右シングルクォート
        '"': '"',  # 左ダブルクォート
        '"': '"',  # 右ダブルクォート
        '‛': "'",  # 反転シングルクォート
        '‟': '"',  # 反転ダブルクォート
        '′': "'",  # プライム
        '″': '"',  # ダブルプライム

        # 三点リーダー
        '…': '...',  # 三点リーダー → ドット3つ
        '⋯': '...',  # 中点三点リーダー

        # チルダ・波ダッシュ系
        '～': '~',  # 全角チルダ
        '∼': '~',  # 波ダッシュ
        '〜': '~',  # 全角チルダ（別）
        '⁓': '~',  # 反転チルダ

        # その他の記号
        '•': '*',  # 黒丸
        '·': '*',  # 中点
        '※': '*',  # 米印
        '°': 'deg',  # 度記号
        '℃': 'C',  # 摂氏
        '℉': 'F',  # 華氏
        '×': 'x',  # 乗算記号
        '÷': '/',  # 除算記号
        '±': '+/-',  # プラスマイナス
        '≒': '=',  # 約等号
        '≠': '!=',  # 不等号
        '≦': '<=',  # 以下
        '≧': '>=',  # 以上
        '∞': 'inf',  # 無限大
        '♪': '(music)',  # 音符
        '♡': '(heart)',  # ハート
        '★': '*',  # 星
        '☆': '*',  # 星（白抜き）
        '→': '->',  # 右矢印
        '←': '<-',  # 左矢印
        '↑': '^',  # 上矢印
        '↓': 'v',  # 下矢印
        '【': '[',  # 墨付きかっこ
        '】': ']',  # 墨付きかっこ
        '《': '<<',  # 二重山かっこ
        '》': '>>',  # 二重山かっこ
        '〈': '<',  # 山かっこ
        '〉': '>',  # 山かっこ
    }

    for old, new in replacements.items():
        if old in s:
            s = s.replace(old, new)

    # 改行・タブを空白に置換（列崩れ防止）
    s = re.sub(r'[\r\n\t]', ' ', s)

    # Shift_JISで変換できない文字を1文字ずつチェック
    try:
        s.encode('cp932')
        # エンコード成功 → そのまま返す
    except UnicodeEncodeError:
        # エンコード失敗 → 1文字ずつチェックして置換
        safe_chars = []
        for i, char in enumerate(s):
            try:
                char.encode('cp932')
                safe_chars.append(char)
            except UnicodeEncodeError:
                # 変換できない文字は ? に置換
                safe_chars.append('?')
        s = ''.join(safe_chars)


    return s

def remove_excel_formula_prefix(s: str) -> str:
    """
    SKU等に含まれる Excel数式表記 ="..." を除去
    例: ="ABC123" → ABC123
    """
    if not isinstance(s, str):
        return str(s) if s is not None else ""

    # ="..." パターンを除去
    s = re.sub(r'^="(.*)"$', r'\1', s)
    # =" で始まる場合も除去
    s = re.sub(r'^="', '', s)
    # " で終わる場合も除去
    s = re.sub(r'"$', '', s)

    return s

def normalize_dataframe_for_cp932(df: pd.DataFrame) -> pd.DataFrame:
    """
    DataFrame全体をShift_JIS (cp932) 出力用に正規化
    1. NaN → 空文字列
    2. SKU列の Excel数式表記除去
    3. 全文字列列をNFKC正規化 + 危険文字除去
    """
    # 1. NaN → 空文字列（"nan"文字列化を防ぐ）
    df = df.fillna("")

    # 2. conditionNote 列は repricer 出力では不要のため削除
    if 'conditionNote' in df.columns:
        df = df.drop(columns=['conditionNote'])

    # 3. 全列の Excel数式表記除去（="..." → 純粋な値）
    for col in df.columns:
        df[col] = df[col].apply(remove_excel_formula_prefix)

    # 4. 全列を明示的に文字列化してから正規化
    for col in df.columns:
        # 数値列以外は明示的に文字列化
        if col not in ['price', 'akaji', 'priceTrace', 'leadtime']:
            df[col] = df[col].astype(str)
        df[col] = df[col].apply(normalize_string_for_cp932)

    # 5. 数値列を数値型に戻す（price, akaji, priceTrace, leadtime等）
    numeric_cols = ['price', 'akaji', 'priceTrace', 'leadtime']
    for col in numeric_cols:
        if col in df.columns:
            # 空文字列の場合は0にする
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    return df

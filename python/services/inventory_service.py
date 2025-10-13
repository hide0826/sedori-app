"""
HIRIO 仕入管理システム
inventory_service.py

作成日: 2025-10-06
"""
import pandas as pd
import chardet
import io
import json
from pathlib import Path
from datetime import datetime
from typing import Tuple, List
from fastapi.responses import StreamingResponse
from utils.csv_io import write_listing_csv

# コンディションマッピング（Amazonコンディション番号）
CONDITION_MAP = {
    "中古(ほぼ新品)": "1",
    "中古(非常に良い)": "2", 
    "中古(良い)": "3",
    "中古(可)": "4",
    "コレクター商品(ほぼ新品)": "5",
    "コレクター商品(非常に良い)": "6",
    "コレクター商品(良い)": "7",
    "コレクター商品(可)": "8",
    "再生品": "10",
    "新品(新品)": "11",
    "新品": "11",
}

# Qタグキーワード
Q3_KEYWORDS = [
    "扇風機", "サーキュレーター", "冷風", "冷感", "クール",
    "虫除け", "虫よけ", "アウトドア", "プール", "水遊び", "水鉄砲", "かき氷"
]

Q4_KEYWORDS = [
    "おもちゃ", "レゴ", "トミカ", "プラレール", "シルバニア",
    "仮面ライダー", "戦隊", "ポケモン", "ベイブレード", "リカちゃん",
    "ドール", "フィギュア", "変身", "アンパンマン",
    "バンダイ", "BANDAI", "たまごっち", "妖怪ウォッチ",
    "加湿器", "ヒーター", "こたつ", "ストーブ", "Nathan", "ボーネルンド", "ウルトラマン"
]

# カウンターファイルパス
COUNTER_FILE = Path("/app/data/sku_counter.json")


def convert_condition(condition_str: str) -> str:
    """
    コンディション文字列を番号に変換
    
    Args:
        condition_str: "中古(非常に良い)" 等
        
    Returns:
        "2" 等のコンディション番号
        不明な場合は "2"（デフォルト: 中古-非常に良い）
    """
    return CONDITION_MAP.get(condition_str, "2")


def detect_q_tag(product_name: str) -> str:
    """
    商品名からQタグを自動判定
    
    Args:
        product_name: 商品名
        
    Returns:
        "Q3" | "Q4" | ""
    """
    if not product_name:
        return ""
    
    product_name_upper = product_name.upper()
    
    # Q4チェック（優先）
    for keyword in Q4_KEYWORDS:
        if keyword.upper() in product_name_upper:
            return "Q4"
    
    # Q3チェック
    for keyword in Q3_KEYWORDS:
        if keyword.upper() in product_name_upper:
            return "Q3"
    
    return ""


def get_next_sequence(date_str: str, condition_code: str) -> int:
    """
    連番カウンターから次の番号を取得・更新
    
    Args:
        date_str: "20241007"
        condition_code: "2"
        
    Returns:
        次の連番（1, 2, 3...）
    """
    # カウンターファイル読み込み
    if COUNTER_FILE.exists():
        with open(COUNTER_FILE, "r", encoding="utf-8") as f:
            counters = json.load(f)
    else:
        counters = {}
    
    # キー生成
    key = f"{date_str}-{condition_code}"
    
    # 次の番号取得
    next_num = counters.get(key, 0) + 1
    
    # カウンター更新
    counters[key] = next_num
    
    # 保存
    COUNTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(COUNTER_FILE, "w", encoding="utf-8") as f:
        json.dump(counters, f, ensure_ascii=False, indent=2)
    
    return next_num


def generate_sku(
    purchase_date: str,
    condition: str,
    product_name: str
) -> str:
    """
    SKU生成: 20241007-2-001-Q4 形式
    
    Args:
        purchase_date: 仕入日 "2024-10-07" または "20241007"
        condition: コンディション文字列 "中古(非常に良い)"
        product_name: 商品名（Qタグ判定用）
        
    Returns:
        生成されたSKU
    """
    # 日付フォーマット統一
    if "-" in purchase_date:
        date_str = purchase_date.replace("-", "")
    else:
        date_str = purchase_date
    
    # コンディション番号変換
    condition_code = convert_condition(condition)
    
    # 連番取得
    sequence = get_next_sequence(date_str, condition_code)
    
    # Qタグ判定
    q_tag = detect_q_tag(product_name)
    
    # SKU組み立て
    sku = f"{date_str}-{condition_code}-{sequence:03d}"
    
    if q_tag:
        sku += f"-{q_tag}"
    
    return sku


def split_by_comment(products: List[dict]) -> Tuple[List[dict], List[dict]]:
    """
    コメント欄の有無で商品を振り分け
    
    Args:
        products: SKU生成済み商品リスト
        
    Returns:
        (出品対象リスト, 出品除外リスト)
    """
    listing_products = []    # コメント空
    excluded_products = []   # コメントあり
    
    for product in products:
        comment = product.get("コメント", "")
        
        # None, 空文字、空白のみをチェック
        if not comment or str(comment).strip() == "":
            listing_products.append(product)
        else:
            excluded_products.append(product)
    
    return listing_products, excluded_products


def generate_listing_csv_content(products: List[dict]) -> bytes:
    """
    出品用CSV生成（CSV I/Oエンジン使用）
    """
    # === デバッグ出力 START ===
    print("\n=== CSV生成デバッグ ===")
    print(f"商品数: {len(products)}")
    
    if products:
        first = products[0]
        print(f"1件目の商品名: {first.get('商品名')}")
        print(f"商品名の型: {type(first.get('商品名'))}")
        
        if first.get('商品名'):
            try:
                utf8_hex = first.get('商品名').encode('utf-8').hex()
                print(f"商品名 UTF-8 hex: {utf8_hex[:40]}...")
                sjis_hex = first.get('商品名').encode('shift-jis').hex()
                print(f"商品名 Shift-JIS hex: {sjis_hex[:40]}...")
            except Exception as e:
                print(f"エンコードエラー: {e}")
        
        print(f"コンディション説明: {first.get('コンディション説明', 'なし')}")
    print("======================\n")
    # === デバッグ出力 END ===
    
    if not products:
        return b""
    
    # 列マッピング（仕入リスト → 出品CSV）
    column_mapping = {
        'sku': 'SKU',
        'ASIN': 'ASIN',
        'JAN': 'JAN',
        '商品名': 'title',
        '仕入れ個数': 'add_number',
        '販売予定価格': 'price',
        '仕入れ価格': 'cost',
        '損益分岐点': 'akaji',
        'コンディション説明': 'conditionNote'
    }
    
    # データ変換
    converted_data = []
    for i, product in enumerate(products):
        row = {}
        
        # === デバッグ: 1件目だけキー確認 ===
        if i == 0:
            print("\n=== product keys確認 ===")
            print(f"productの全キー: {list(product.keys())}")
            print(f"商品名の値: {product.get('商品名', 'キーなし')}")
            print(f"title への変換: {product.get('商品名')}")
            print("========================\n")
        # =====================================
        
        # 列マッピング適用
        for src, dst in column_mapping.items():
            if src in product:
                row[dst] = product[src]
        
        # コンディション番号変換
        if 'コンディション' in product:
            row['condition'] = convert_condition(product['コンディション'])
        
        # takane = 販売予定価格
        if 'price' in row:
            row['takane'] = row['price']
        
        # 空欄列
        row.setdefault('priceTrace', '')
        row.setdefault('leadtime', '')
        row.setdefault('merchant_shipping_group_name', '')
        
        converted_data.append(row)
    
    # 出品CSV列順序
    columns = [
        'SKU', 'ASIN', 'JAN', 'title', 'add_number', 'price', 
        'cost', 'akaji', 'takane', 'condition', 'conditionNote', 
        'priceTrace', 'leadtime', 'merchant_shipping_group_name'
    ]
    
    # CSV生成
    # === デバッグ: 変換後データ確認 ===
    print("\n=== converted_data確認 ===")
    print(f"変換後データ件数: {len(converted_data)}")
    if converted_data:
        first = converted_data[0]
        print(f"1件目のtitle: {first.get('title', 'なし')}")
        print(f"title の型: {type(first.get('title'))}")
        print(f"1件目のconditionNote: {first.get('conditionNote', 'なし')}")
        print(f"全キー: {list(first.keys())}")
    print("===========================\n")
    # ====================================
    
    csv_bytes = write_listing_csv(
        data=converted_data,
        columns=columns,
        excel_formula_cols=[]  # 参考CSVに合わせて数式記法なし
    )
    
    # === デバッグ: 生成されたCSVの先頭確認 ===
    print("\n=== 生成CSV確認 ===")
    print(f"CSV bytes長: {len(csv_bytes)}")
    
    # 実ファイルとして保存
    debug_file = Path("/app/data/debug_output.csv")
    debug_file.parent.mkdir(parents=True, exist_ok=True)
    with open(debug_file, "wb") as f:
        f.write(csv_bytes)
    print(f"デバッグファイル保存: {debug_file}")
    
    # 全体をShift-JISでデコードしてみる
    try:
        decoded_full = csv_bytes.decode('shift-jis', errors='replace')
        lines = decoded_full.split('\n')
        print(f"CSVの行数: {len(lines)}")
        print("先頭3行:")
        for i, line in enumerate(lines[:3]):
            print(f"  {i}: {line}")
    except Exception as e:
        print(f"デコードエラー: {e}")
    print("==================\n")
    # =========================================
    
    return csv_bytes


async def process_inventory_csv(file_content: bytes) -> Tuple[pd.DataFrame, dict]:
    """
    仕入リストCSVを処理
    
    Args:
        file_content: CSVファイルのバイトデータ
    
    Returns:
        DataFrame: 処理済みデータ
        dict: 処理結果の統計情報
    """
    # 1. エンコーディング自動判定
    detected = chardet.detect(file_content)
    encoding = detected['encoding']
    
    # 2. CSV読み込み（JAN列を文字列として保持）
    df = pd.read_csv(
        io.BytesIO(file_content),
        encoding=encoding,
        dtype={'JAN': str}
    )
    
    # 3. JAN列の科学的記数法を数値文字列に変換
    if 'JAN' in df.columns:
        def fix_jan(val):
            if pd.isna(val) or val is None:
                return None
            try:
                # 科学的記数法（例: 4.9016E+12）を数値に変換後、整数文字列化
                if 'E' in str(val).upper():
                    return str(int(float(val)))
                return str(val)
            except:
                return str(val)
        
        df['JAN'] = df['JAN'].apply(fix_jan)
    
    # 4. NaN/Infinity値をNoneに変換（JSON互換性のため）
    df = df.replace({float('nan'): None, float('inf'): None, float('-inf'): None})
    
    # 5. 統計情報
    stats = {
        "total_rows": len(df),
        "columns": list(df.columns),
        "encoding": encoding
    }
    
    return df, stats

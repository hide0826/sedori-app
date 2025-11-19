#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
既存レシート画像ファイル名を新しい形式に一括移行

新しい形式: {YYYYMMDD}_{store_code}_{receipt_id}.{拡張子}
"""
from pathlib import Path
import sys
from datetime import datetime

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from desktop.database.receipt_db import ReceiptDatabase


def migrate_receipt_filenames():
    """既存レシート画像ファイル名を新しい形式に一括移行"""
    db = ReceiptDatabase()
    receipts = db.find_by_date_and_store(None)
    
    migrated = 0
    errors = 0
    skipped = 0
    
    print(f"移行開始: {len(receipts)}件のレシートを処理します...\n")
    
    for receipt in receipts:
        receipt_id = receipt.get('id')
        file_path = receipt.get('file_path')
        purchase_date = receipt.get('purchase_date')
        store_code = receipt.get('store_code') or "UNKNOWN"
        
        if not file_path:
            skipped += 1
            print(f"⏭  ID {receipt_id}: ファイルパスがありません")
            continue
        
        current_path = Path(file_path)
        
        if not current_path.exists():
            skipped += 1
            print(f"⏭  ID {receipt_id}: ファイルが存在しません ({file_path})")
            continue
        
        # 新しいファイル名を生成: {YYYYMMDD}_{store_code}_{receipt_id}.{拡張子}
        date_str = purchase_date.replace("-", "") if purchase_date else "UNKNOWN"
        if len(date_str) == 10:  # yyyy-MM-dd形式
            date_str = date_str[:4] + date_str[5:7] + date_str[8:10]
        elif len(date_str) != 8:
            date_str = "UNKNOWN"
        
        new_name = f"{date_str}_{store_code}_{receipt_id}{current_path.suffix}"
        new_path = current_path.parent / new_name
        
        # 既に正しい名前の場合はスキップ
        if current_path.name == new_name:
            skipped += 1
            print(f"✓  ID {receipt_id}: 既に正しい名前です ({new_name})")
            continue
        
        try:
            # 同名ファイルが存在する場合はエラー
            if new_path.exists():
                errors += 1
                print(f"✗  ID {receipt_id}: 同名ファイルが既に存在します ({new_name})")
                continue
            
            # ファイルをリネーム
            current_path.rename(new_path)
            
            # DBのfile_pathを更新
            db.update_receipt(receipt_id, {"file_path": str(new_path)})
            
            migrated += 1
            print(f"✓  ID {receipt_id}: {current_path.name} → {new_name}")
        except Exception as e:
            errors += 1
            print(f"✗  ID {receipt_id}: {current_path.name} - エラー: {e}")
    
    print(f"\n移行完了:")
    print(f"  成功: {migrated}件")
    print(f"  スキップ: {skipped}件")
    print(f"  エラー: {errors}件")


if __name__ == "__main__":
    try:
        migrate_receipt_filenames()
    except KeyboardInterrupt:
        print("\n\n移行が中断されました。")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nエラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


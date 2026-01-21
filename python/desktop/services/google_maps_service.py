#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Maps APIを使用した店舗情報取得サービス

店舗名から住所・電話番号を取得する機能を提供

注意:
- `requests`ライブラリが必要です（通常は標準でインストール済み）
- APIキーは QSettings("HIRIO", "DesktopApp") の "ocr/gemini_api_key" から読み込みます。
  （Gemini APIキーにMaps APIの権限を付与したものを使用）
- 新しいPlaces API (New) を使用します
"""

import os
import json
from typing import Dict, Optional

from PySide6.QtCore import QSettings

try:
    import requests
except ImportError:
    requests = None


def get_store_info_from_google(store_name: str, api_key: Optional[str] = None, language_code: str = 'ja') -> Optional[Dict[str, str]]:
    """
    店舗名からGoogle Maps APIを使用して住所・電話番号を取得
    
    Args:
        store_name: 店舗名（例: "BOOKOFF SUPER BAZAAR 14号千葉幕張店"）
        api_key: APIキー（省略時は設定から取得）
        language_code: 言語コード（デフォルト: 'ja' 日本語）
    
    Returns:
        辞書型 {'address': '...', 'phone': '...'} または None
    """
    if requests is None:
        error_msg = (
            "警告: requestsライブラリがインストールされていません。\n"
            "インストール方法: pip install requests"
        )
        print(error_msg)
        return None
    
    # APIキーを取得（引数がなければ設定から取得）
    if api_key is None:
        settings = QSettings("HIRIO", "DesktopApp")
        api_key = settings.value("ocr/gemini_api_key", "") or None
        
        # 設定から取得できない場合は環境変数から取得（後方互換性のため）
        if not api_key:
            api_key = os.environ.get("GOOGLE_MAPS_API_KEY") or os.environ.get("Maps_API_KEY") or None
    
    if not api_key:
        print("警告: Google Maps APIキーが設定されていません。")
        print("設定タブの「OCR設定」でGemini APIキーを設定してください。")
        print("（Gemini APIキーにMaps APIの権限を付与してください）")
        return None
    
    try:
        # 新しいPlaces API (New) を使用
        # 1. Text Searchで店舗を検索
        search_url = "https://places.googleapis.com/v1/places:searchText"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress"
        }
        
        search_payload = {
            "textQuery": store_name,
            "maxResultCount": 1,
            "languageCode": language_code
        }
        
        search_response = requests.post(search_url, headers=headers, json=search_payload)
        search_response.raise_for_status()
        search_data = search_response.json()
        
        if not search_data.get('places') or len(search_data['places']) == 0:
            print(f"店舗が見つかりませんでした: {store_name}")
            return None
        
        place = search_data['places'][0]
        place_id = place.get('id')
        
        if not place_id:
            print(f"店舗IDが取得できませんでした: {store_name}")
            return None
        
        # 2. Place Detailsで詳細情報を取得
        details_url = f"https://places.googleapis.com/v1/places/{place_id}"
        details_headers = {
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "formattedAddress,nationalPhoneNumber,internationalPhoneNumber"
        }
        
        # 言語パラメータをクエリパラメータとして追加
        details_params = {
            "languageCode": language_code
        }
        
        details_response = requests.get(details_url, headers=details_headers, params=details_params)
        details_response.raise_for_status()
        details_data = details_response.json()
        
        # 住所と電話番号を取得
        address = details_data.get("formattedAddress", "") or ""
        phone = details_data.get("nationalPhoneNumber", "") or details_data.get("internationalPhoneNumber", "") or ""
        
        # 両方とも空の場合はNoneを返す
        if not address and not phone:
            return None
        
        return {
            "address": address,
            "phone": phone
        }
        
    except requests.exceptions.RequestException as e:
        print(f"店舗情報の取得エラー ({store_name}): APIリクエストエラー - {e}")
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_data = e.response.json()
                print(f"エラー詳細: {error_data}")
            except:
                print(f"エラーレスポンス: {e.response.text}")
        return None
    except Exception as e:
        print(f"店舗情報の取得エラー ({store_name}): {e}")
        return None


def recover_store_info_with_japanese(store_db, api_key: Optional[str] = None) -> Dict[str, int]:
    """
    住所に"Japan"が含まれている店舗の情報を日本語で再取得して更新
    
    Args:
        store_db: StoreDatabaseインスタンス
        api_key: APIキー（省略時は設定から取得）
    
    Returns:
        辞書型 {'total': 総数, 'updated': 更新成功数, 'failed': 失敗数}
    """
    # 型チェックは実行時にスキップ（相対インポートの問題を回避）
    # store_dbは既にStoreDatabaseインスタンスとして渡されることが保証されている
    
    # APIキーを取得
    if api_key is None:
        settings = QSettings("HIRIO", "DesktopApp")
        api_key = settings.value("ocr/gemini_api_key", "") or None
        
        if not api_key:
            api_key = os.environ.get("GOOGLE_MAPS_API_KEY") or os.environ.get("Maps_API_KEY") or None
    
    if not api_key:
        print("警告: Google Maps APIキーが設定されていません。")
        return {'total': 0, 'updated': 0, 'failed': 0}
    
    # 住所に"Japan"が含まれているレコードを抽出
    conn = store_db._get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, store_name, address, phone
        FROM stores
        WHERE address LIKE '%Japan%' OR address LIKE '%JAPAN%' OR address LIKE '%japan%'
    """)
    
    stores_to_recover = []
    for row in cursor.fetchall():
        stores_to_recover.append({
            'id': row['id'],
            'store_name': row['store_name'],
            'address': row['address'],
            'phone': row['phone']
        })
    
    total = len(stores_to_recover)
    updated = 0
    failed = 0
    
    print(f"リカバリー対象: {total}件の店舗が見つかりました")
    
    for store in stores_to_recover:
        store_id = store['id']
        store_name = store['store_name']
        
        if not store_name:
            print(f"スキップ: ID {store_id} - 店舗名が空です")
            failed += 1
            continue
        
        print(f"処理中: {store_name} (ID: {store_id})")
        
        # 日本語で再取得
        info = get_store_info_from_google(store_name, api_key=api_key, language_code='ja')
        
        if info and (info.get('address') or info.get('phone')):
            # データベースを更新
            try:
                existing_store = store_db.get_store(store_id)
                if existing_store:
                    # 住所と電話番号を更新
                    if info.get('address'):
                        existing_store['address'] = info['address']
                    if info.get('phone'):
                        existing_store['phone'] = info['phone']
                    
                    store_db.update_store(store_id, existing_store)
                    updated += 1
                    print(f"  更新成功: 住所={info.get('address', 'N/A')[:50]}...")
                else:
                    print(f"  エラー: 店舗ID {store_id} が見つかりません")
                    failed += 1
            except Exception as e:
                print(f"  更新エラー: {e}")
                failed += 1
        else:
            print(f"  情報取得失敗")
            failed += 1
    
    return {
        'total': total,
        'updated': updated,
        'failed': failed
    }






#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Cloud Storage (GCS) 画像アップロードユーティリティ

画像ファイルをGCSにアップロードし、公開URLを取得する。
"""
from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# GCS設定定数
BUCKET_NAME = "hirio-images-main"
# サービスアカウントキーのパス（絶対パス）
KEY_PATH = r"D:\HIRIO\repo\sedori-app.github\python\desktop\data\credentials\service_account_key.json"

try:
    from google.cloud import storage
    GCS_AVAILABLE = True
except ImportError:
    storage = None
    GCS_AVAILABLE = False
    logger.warning("google-cloud-storage is not installed. GCS upload functionality will be disabled.")


def _get_content_type(file_path: str) -> str:
    """
    ファイル拡張子から適切なcontent_typeを判定
    
    Args:
        file_path: ファイルパス
        
    Returns:
        content_type文字列
    """
    ext = Path(file_path).suffix.lower()
    content_type_map = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.bmp': 'image/bmp',
        '.webp': 'image/webp',
        '.tiff': 'image/tiff',
        '.tif': 'image/tiff',
    }
    return content_type_map.get(ext, 'image/jpeg')  # デフォルトはjpeg


def upload_image_to_gcs(
    source_file_path: str,
    destination_blob_name: Optional[str] = None
) -> str:
    """
    画像ファイルをGCSにアップロードし、公開URLを取得する
    
    Args:
        source_file_path: アップロードする画像ファイルのパス
        destination_blob_name: GCS上の保存先パス（指定しない場合は自動生成）
        
    Returns:
        公開URL（https://storage.googleapis.com/{BUCKET_NAME}/{destination_blob_name}）
        
    Raises:
        FileNotFoundError: ソースファイルまたはサービスアカウントキーが見つからない場合
        ImportError: google-cloud-storageがインストールされていない場合
        Exception: その他のアップロードエラー
    """
    if not GCS_AVAILABLE:
        raise ImportError(
            "google-cloud-storage is not installed. "
            "Please install it with: pip install google-cloud-storage"
        )
    
    # ソースファイルの存在確認
    source_path = Path(source_file_path)
    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_file_path}")
    
    # サービスアカウントキーの存在確認
    key_path = Path(KEY_PATH)
    if not key_path.exists():
        raise FileNotFoundError(
            f"Service account key file not found: {KEY_PATH}\n"
            f"Please ensure the service account key is placed at the specified path."
        )
    
    try:
        # GCSクライアントの初期化
        client = storage.Client.from_service_account_json(str(key_path))
        bucket = client.bucket(BUCKET_NAME)
        
        # アップロード先パスの生成
        if destination_blob_name is None:
            # 日付プレフィックスとused_items/プレフィックスを付与
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_name = source_path.name
            destination_blob_name = f"used_items/{timestamp}_{file_name}"
        
        # Blobオブジェクトの作成
        blob = bucket.blob(destination_blob_name)
        
        # Content-Typeの設定
        content_type = _get_content_type(source_file_path)
        blob.content_type = content_type
        
        # ファイルのアップロード
        logger.info(f"Uploading {source_file_path} to gs://{BUCKET_NAME}/{destination_blob_name}")
        blob.upload_from_filename(str(source_path))
        
        # 公開URLの生成
        public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{destination_blob_name}"
        
        logger.info(f"Upload successful. Public URL: {public_url}")
        return public_url
        
    except FileNotFoundError:
        raise
    except Exception as e:
        logger.error(f"Failed to upload image to GCS: {e}", exc_info=True)
        raise Exception(f"GCS upload failed: {str(e)}") from e


if __name__ == "__main__":
    # 動作確認用のダミーファイルパス
    # 実際のファイルパスに置き換えてテストしてください
    test_file_path = r"D:\HIRIO\repo\sedori-app.github\python\scripts\test_image.jpg"
    
    print("GCS Image Uploader Test")
    print("=" * 50)
    print(f"Bucket: {BUCKET_NAME}")
    print(f"Service Account Key: {KEY_PATH}")
    print(f"Test File: {test_file_path}")
    print("=" * 50)
    
    try:
        # テストファイルの存在確認
        if not Path(test_file_path).exists():
            print(f"\n⚠️  Warning: Test file not found: {test_file_path}")
            print("Please update the test_file_path variable with a valid image file path.")
        else:
            # アップロード実行
            print("\nUploading image...")
            public_url = upload_image_to_gcs(test_file_path)
            print(f"\n✅ Upload successful!")
            print(f"Public URL: {public_url}")
    except FileNotFoundError as e:
        print(f"\n❌ Error: {e}")
    except ImportError as e:
        print(f"\n❌ Error: {e}")
        print("\nTo install google-cloud-storage, run:")
        print("  pip install google-cloud-storage")
    except Exception as e:
        print(f"\n❌ Error: {e}")


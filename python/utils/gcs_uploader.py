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
except ImportError as e:
    storage = None
    GCS_AVAILABLE = False
    logger.warning(f"google-cloud-storage is not installed. GCS upload functionality will be disabled. Error: {e}")


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


def check_gcs_authentication() -> tuple:
    """
    GCS認証を確認する
    
    Returns:
        (success: bool, error_message: Optional[str])
        successがTrueの場合、認証は成功
        successがFalseの場合、error_messageにエラー内容が含まれる
    """
    if not GCS_AVAILABLE:
        return False, "google-cloud-storageがインストールされていません。"
    
    key_path = Path(KEY_PATH)
    if not key_path.exists():
        return False, f"サービスアカウントキーファイルが見つかりません: {KEY_PATH}"
    
    try:
        import json
        with open(key_path, 'r', encoding='utf-8') as f:
            key_data = json.load(f)
        if 'type' not in key_data or key_data.get('type') != 'service_account':
            return False, "サービスアカウントキーの形式が無効です。"
    except json.JSONDecodeError:
        return False, "サービスアカウントキーファイルが有効なJSONではありません。"
    except Exception as e:
        return False, f"サービスアカウントキーファイルの読み込みに失敗: {str(e)}"
    
    try:
        client = storage.Client.from_service_account_json(str(key_path))
        bucket = client.bucket(BUCKET_NAME)
        # 軽量な操作で認証を確認
        bucket.reload()
        return True, None
    except Exception as e:
        error_msg = str(e).lower()
        if 'invalid' in error_msg or 'credentials' in error_msg or 'authentication' in error_msg:
            return False, f"認証エラー: サービスアカウントキーが無効です。\n詳細: {str(e)}"
        elif 'permission' in error_msg or 'access' in error_msg or '403' in error_msg:
            return False, f"権限エラー: バケット '{BUCKET_NAME}' へのアクセス権限がありません。"
        elif 'not found' in error_msg or '404' in error_msg:
            return False, f"バケットが見つかりません: {BUCKET_NAME}"
        else:
            return False, f"認証確認に失敗: {str(e)}"


def upload_image_to_gcs(
    source_file_path: str,
    destination_blob_name: Optional[str] = None,
    storage_class: Optional[str] = None
) -> str:
    """
    画像ファイルをGCSにアップロードし、公開URLを取得する
    
    Args:
        source_file_path: アップロードする画像ファイルのパス
        destination_blob_name: GCS上の保存先パス（指定しない場合は自動生成）
        storage_class: ストレージクラス（STANDARD, COLDLINE, ARCHIVE など。Noneの場合はSTANDARD）
        
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
    
    # サービスアカウントキーファイルの形式確認
    try:
        import json
        with open(key_path, 'r', encoding='utf-8') as f:
            key_data = json.load(f)
        # 必須フィールドの確認
        if 'type' not in key_data or key_data.get('type') != 'service_account':
            raise ValueError("Invalid service account key format: 'type' field is missing or incorrect")
        if 'project_id' not in key_data:
            raise ValueError("Invalid service account key format: 'project_id' field is missing")
        if 'private_key' not in key_data:
            raise ValueError("Invalid service account key format: 'private_key' field is missing")
    except json.JSONDecodeError as e:
        raise ValueError(f"Service account key file is not valid JSON: {str(e)}")
    except Exception as e:
        if isinstance(e, (ValueError, FileNotFoundError)):
            raise
        raise ValueError(f"Failed to read service account key file: {str(e)}")
    
    try:
        # GCSクライアントの初期化
        try:
            client = storage.Client.from_service_account_json(str(key_path))
        except Exception as e:
            error_msg = str(e).lower()
            if 'invalid' in error_msg or 'credentials' in error_msg or 'authentication' in error_msg:
                raise ValueError(
                    f"認証エラー: サービスアカウントキーが無効です。\n"
                    f"キーファイルの内容、有効期限、権限を確認してください。\n"
                    f"詳細: {str(e)}"
                )
            elif 'permission' in error_msg or 'access' in error_msg:
                raise ValueError(
                    f"権限エラー: サービスアカウントに必要な権限がありません。\n"
                    f"Storage Admin または Storage Object Admin の権限が必要です。\n"
                    f"詳細: {str(e)}"
                )
            else:
                raise ValueError(f"GCSクライアントの初期化に失敗しました: {str(e)}")
        
        # バケットへのアクセス確認
        try:
            bucket = client.bucket(BUCKET_NAME)
            # バケットの存在確認（軽量な操作で認証を確認）
            bucket.reload()
        except Exception as e:
            error_msg = str(e).lower()
            if 'not found' in error_msg or '404' in error_msg:
                raise ValueError(
                    f"バケットが見つかりません: {BUCKET_NAME}\n"
                    f"バケット名が正しいか、プロジェクトが正しいか確認してください。"
                )
            elif 'permission' in error_msg or 'access' in error_msg or '403' in error_msg:
                raise ValueError(
                    f"権限エラー: バケット '{BUCKET_NAME}' へのアクセス権限がありません。\n"
                    f"サービスアカウントに Storage Admin または Storage Object Admin の権限が必要です。"
                )
            elif 'invalid' in error_msg or 'credentials' in error_msg or 'authentication' in error_msg:
                raise ValueError(
                    f"認証エラー: バケットへのアクセスに失敗しました。\n"
                    f"サービスアカウントキーが有効か確認してください。\n"
                    f"詳細: {str(e)}"
                )
            else:
                raise ValueError(f"バケットへのアクセスに失敗しました: {str(e)}")
        
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
        
        # ストレージクラスの設定（指定がある場合）
        if storage_class:
            blob.storage_class = storage_class
        
        # ファイルのアップロード
        logger.info(f"Uploading {source_file_path} to gs://{BUCKET_NAME}/{destination_blob_name} (storage_class: {storage_class or 'STANDARD'})")
        blob.upload_from_filename(str(source_path))
        
        # 公開URLの生成
        public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{destination_blob_name}"
        
        logger.info(f"Upload successful. Public URL: {public_url}")
        return public_url
        
    except (FileNotFoundError, ValueError, ImportError):
        # これらのエラーはそのまま再スロー（詳細なメッセージが含まれている）
        raise
    except Exception as e:
        error_msg = str(e).lower()
        # 認証関連のエラーを検出
        if 'invalid' in error_msg or 'credentials' in error_msg or 'authentication' in error_msg:
            logger.error(f"GCS authentication error: {e}", exc_info=True)
            raise ValueError(
                f"認証エラー: GCSへの認証に失敗しました。\n"
                f"サービスアカウントキーが有効か、権限が正しいか確認してください。\n"
                f"詳細: {str(e)}"
            )
        elif 'permission' in error_msg or 'access' in error_msg or '403' in error_msg:
            logger.error(f"GCS permission error: {e}", exc_info=True)
            raise ValueError(
                f"権限エラー: GCSへのアクセス権限がありません。\n"
                f"サービスアカウントに Storage Admin または Storage Object Admin の権限が必要です。\n"
                f"詳細: {str(e)}"
            )
        else:
            logger.error(f"Failed to upload image to GCS: {e}", exc_info=True)
            raise Exception(f"GCS upload failed: {str(e)}") from e


def find_existing_public_url_for_local_file(
    source_file_path: str,
    prefix: str = "used_items/",
) -> Optional[str]:
    """
    ローカル画像ファイル名でGCS上の既存ファイルを検索し、見つかれば公開URLを返す。

    注意:
    - 本プロジェクトのアップロード先は timestamp を含むため、完全一致ではなく「末尾が同じファイル名」のblobを探す。
    - バケット内のオブジェクト数が非常に多い場合は検索が重くなる可能性がある。
    """
    if not GCS_AVAILABLE:
        return None

    source_path = Path(source_file_path)
    if not source_path.exists():
        return None

    key_path = Path(KEY_PATH)
    if not key_path.exists():
        return None

    file_name = source_path.name

    try:
        client = storage.Client.from_service_account_json(str(key_path))
        bucket = client.bucket(BUCKET_NAME)

        # prefix配下のblobを走査し、末尾がファイル名一致するものを探す
        latest_blob = None
        latest_updated = None
        for blob in client.list_blobs(BUCKET_NAME, prefix=prefix):
            if not getattr(blob, "name", ""):
                continue
            if not blob.name.endswith(file_name):
                continue
            updated = getattr(blob, "updated", None)
            if latest_blob is None:
                latest_blob = blob
                latest_updated = updated
            else:
                # updatedが比較できる場合は新しい方を優先
                try:
                    if updated and (latest_updated is None or updated > latest_updated):
                        latest_blob = blob
                        latest_updated = updated
                except Exception:
                    # 比較に失敗したら最初に見つかったものを維持
                    pass

        if latest_blob is None:
            return None

        return f"https://storage.googleapis.com/{BUCKET_NAME}/{latest_blob.name}"
    except Exception as e:
        logger.warning(f"Failed to find existing blob for {source_file_path}: {e}")
        return None


def set_bucket_lifecycle_policy(
    year1_storage: str = "STANDARD",
    year2_7_storage: str = "COLDLINE",
    year8_10_storage: str = "ARCHIVE",
    enable_auto_delete: bool = False
) -> bool:
    """
    バケットのライフサイクル管理ポリシーを設定する
    
    Args:
        year1_storage: 1年目のストレージクラス（STANDARD, COLDLINE, ARCHIVE）
        year2_7_storage: 2年目～7年目のストレージクラス
        year8_10_storage: 8年目～10年目のストレージクラス
        enable_auto_delete: 10年経過後の自動削除を有効にするか
    
    Returns:
        成功した場合True、失敗した場合False
    """
    if not GCS_AVAILABLE:
        logger.error("google-cloud-storage is not installed")
        return False
    
    key_path = Path(KEY_PATH)
    if not key_path.exists():
        logger.error(f"Service account key file not found: {KEY_PATH}")
        return False
    
    try:
        client = storage.Client.from_service_account_json(str(key_path))
        bucket = client.bucket(BUCKET_NAME)
        bucket.reload()
        
        # ライフサイクル管理ルールを構築
        rules = []
        
        # 1年経過後: year1_storage → year2_7_storage へ移行
        if year1_storage != year2_7_storage:
            rules.append({
                "action": {"type": "SetStorageClass", "storageClass": year2_7_storage},
                "condition": {"age": 365}  # 1年 = 365日
            })
        
        # 7年経過後: year2_7_storage → year8_10_storage へ移行
        if year2_7_storage != year8_10_storage:
            rules.append({
                "action": {"type": "SetStorageClass", "storageClass": year8_10_storage},
                "condition": {"age": 2555}  # 7年 = 2555日
            })
        
        # 10年経過後: 自動削除（オプション）
        if enable_auto_delete:
            rules.append({
                "action": {"type": "Delete"},
                "condition": {"age": 3650}  # 10年 = 3650日
            })
        
        # バケットのライフサイクル管理ポリシーを設定
        if rules:
            try:
                from google.cloud.storage.bucket import LifecycleConfiguration
                lifecycle = LifecycleConfiguration()
                
                # 各ルールを追加
                for rule in rules:
                    action_type = rule["action"]["type"]
                    if action_type == "SetStorageClass":
                        storage_class = rule["action"]["storageClass"]
                        age = rule["condition"]["age"]
                        lifecycle.add_lifecycle_set_storage_class_rule(age=age, storage_class=storage_class)
                    elif action_type == "Delete":
                        age = rule["condition"]["age"]
                        lifecycle.add_lifecycle_delete_rule(age=age)
                
                bucket.lifecycle = lifecycle
                bucket.update()
                logger.info(f"Lifecycle policy set: {len(rules)} rules")
                return True
            except ImportError:
                # LifecycleConfigurationが利用できない場合は、直接辞書形式で設定を試行
                try:
                    lifecycle_dict = {"rule": rules}
                    bucket.lifecycle = lifecycle_dict
                    bucket.update()
                    logger.info(f"Lifecycle policy set (dict format): {len(rules)} rules")
                    return True
                except Exception as e:
                    logger.error(f"Failed to set lifecycle policy (dict format): {e}")
                    return False
            except Exception as e:
                logger.error(f"Failed to set lifecycle policy: {e}", exc_info=True)
                return False
        else:
            logger.warning("No lifecycle rules to set")
            return False
            
    except Exception as e:
        logger.error(f"Failed to set lifecycle policy: {e}", exc_info=True)
        return False


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


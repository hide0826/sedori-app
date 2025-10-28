#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CSV操作ユーティリティ

ファイルダイアログ、エンコーディング判定、CSV操作
"""

import pandas as pd
import chardet
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import logging


class CSVIO:
    """CSV操作ユーティリティクラス"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
    def detect_encoding(self, file_path: str) -> str:
        """ファイルのエンコーディングを検出"""
        try:
            with open(file_path, 'rb') as f:
                raw_data = f.read()
                result = chardet.detect(raw_data)
                encoding = result['encoding']
                confidence = result['confidence']
                
                self.logger.info(f"エンコーディング検出: {encoding} (信頼度: {confidence:.2f})")
                
                # 信頼度が低い場合はデフォルトエンコーディングを使用
                if confidence < 0.7:
                    self.logger.warning(f"エンコーディング検出の信頼度が低い: {confidence:.2f}")
                    return 'utf-8'
                
                return encoding
                
        except Exception as e:
            self.logger.error(f"エンコーディング検出失敗: {e}")
            return 'utf-8'  # デフォルト
    
    def read_csv(self, file_path: str, encoding: Optional[str] = None) -> Optional[pd.DataFrame]:
        """CSVファイルの読み込み"""
        try:
            if encoding is None:
                encoding = self.detect_encoding(file_path)
            
            # 複数のエンコーディングを試行
            encodings_to_try = [encoding, 'utf-8', 'shift_jis', 'cp932', 'euc-jp']
            
            for enc in encodings_to_try:
                try:
                    df = pd.read_csv(file_path, encoding=enc)
                    self.logger.info(f"CSV読み込み成功: {file_path} (エンコーディング: {enc})")
                    return df
                except UnicodeDecodeError:
                    continue
                except Exception as e:
                    self.logger.error(f"CSV読み込みエラー ({enc}): {e}")
                    continue
            
            self.logger.error(f"すべてのエンコーディングでCSV読み込み失敗: {file_path}")
            return None
            
        except Exception as e:
            self.logger.error(f"CSV読み込み失敗: {e}")
            return None
    
    def save_csv(self, df: pd.DataFrame, file_path: str, encoding: str = 'utf-8-sig') -> bool:
        """CSVファイルの保存"""
        try:
            # ディレクトリの作成
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)
            
            # CSV保存
            df.to_csv(file_path, index=False, encoding=encoding)
            self.logger.info(f"CSV保存成功: {file_path} (エンコーディング: {encoding})")
            return True
            
        except Exception as e:
            self.logger.error(f"CSV保存失敗: {e}")
            return False
    
    def validate_csv_structure(self, df: pd.DataFrame, expected_columns: List[str]) -> Tuple[bool, List[str]]:
        """CSV構造の検証"""
        errors = []
        
        # 必須列のチェック
        missing_columns = set(expected_columns) - set(df.columns)
        if missing_columns:
            errors.append(f"必須列が不足: {list(missing_columns)}")
        
        # データ型のチェック
        for column in df.columns:
            if df[column].dtype == 'object':
                # 文字列列の空値チェック
                null_count = df[column].isnull().sum()
                if null_count > 0:
                    errors.append(f"列 '{column}' に {null_count} 個の空値があります")
        
        # 行数のチェック
        if len(df) == 0:
            errors.append("データが空です")
        
        is_valid = len(errors) == 0
        return is_valid, errors
    
    def normalize_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """データの正規化"""
        try:
            # 文字列列の前後空白を削除
            for column in df.columns:
                if df[column].dtype == 'object':
                    df[column] = df[column].astype(str).str.strip()
            
            # 数値列の正規化
            numeric_columns = ['価格', '原価', '利益', '数量']
            for column in numeric_columns:
                if column in df.columns:
                    df[column] = pd.to_numeric(df[column], errors='coerce')
            
            # 日付列の正規化
            date_columns = ['仕入日', '出品日', '売上日']
            for column in date_columns:
                if column in df.columns:
                    df[column] = pd.to_datetime(df[column], errors='coerce')
            
            self.logger.info("データ正規化完了")
            return df
            
        except Exception as e:
            self.logger.error(f"データ正規化失敗: {e}")
            return df
    
    def get_file_info(self, file_path: str) -> Dict[str, Any]:
        """ファイル情報の取得"""
        try:
            path = Path(file_path)
            if not path.exists():
                return {'exists': False}
            
            # 基本情報
            info = {
                'exists': True,
                'name': path.name,
                'size': path.stat().st_size,
                'modified': path.stat().st_mtime,
                'extension': path.suffix.lower()
            }
            
            # CSVファイルの場合、詳細情報を追加
            if info['extension'] == '.csv':
                df = self.read_csv(file_path)
                if df is not None:
                    info.update({
                        'rows': len(df),
                        'columns': len(df.columns),
                        'column_names': df.columns.tolist(),
                        'encoding': self.detect_encoding(file_path)
                    })
            
            return info
            
        except Exception as e:
            self.logger.error(f"ファイル情報取得失敗: {e}")
            return {'exists': False, 'error': str(e)}
    
    def export_to_excel(self, df: pd.DataFrame, file_path: str) -> bool:
        """Excelファイルへの出力"""
        try:
            # ディレクトリの作成
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)
            
            # Excel保存
            with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='データ', index=False)
            
            self.logger.info(f"Excel保存成功: {file_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Excel保存失敗: {e}")
            return False
    
    def merge_csv_files(self, file_paths: List[str], output_path: str) -> bool:
        """複数CSVファイルの結合"""
        try:
            dataframes = []
            
            for file_path in file_paths:
                df = self.read_csv(file_path)
                if df is not None:
                    dataframes.append(df)
                else:
                    self.logger.warning(f"ファイル読み込み失敗: {file_path}")
            
            if not dataframes:
                self.logger.error("結合可能なファイルがありません")
                return False
            
            # データフレームの結合
            merged_df = pd.concat(dataframes, ignore_index=True)
            
            # 重複行の削除
            merged_df = merged_df.drop_duplicates()
            
            # 保存
            success = self.save_csv(merged_df, output_path)
            
            if success:
                self.logger.info(f"CSV結合成功: {len(dataframes)}ファイル → {output_path}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"CSV結合失敗: {e}")
            return False
    
    def split_csv_by_column(self, df: pd.DataFrame, column: str, output_dir: str) -> List[str]:
        """列の値でCSVファイルを分割"""
        try:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            
            output_files = []
            
            for value in df[column].unique():
                if pd.isna(value):
                    continue
                
                # 値でフィルタリング
                filtered_df = df[df[column] == value]
                
                # ファイル名の生成
                safe_value = str(value).replace('/', '_').replace('\\', '_')
                output_file = output_dir / f"{safe_value}.csv"
                
                # 保存
                if self.save_csv(filtered_df, str(output_file)):
                    output_files.append(str(output_file))
            
            self.logger.info(f"CSV分割完了: {len(output_files)}ファイル生成")
            return output_files
            
        except Exception as e:
            self.logger.error(f"CSV分割失敗: {e}")
            return []
    
    def get_column_statistics(self, df: pd.DataFrame) -> Dict[str, Any]:
        """列の統計情報を取得"""
        try:
            stats = {}
            
            for column in df.columns:
                column_stats = {
                    'type': str(df[column].dtype),
                    'count': df[column].count(),
                    'null_count': df[column].isnull().sum(),
                    'unique_count': df[column].nunique()
                }
                
                # 数値列の場合
                if pd.api.types.is_numeric_dtype(df[column]):
                    column_stats.update({
                        'mean': df[column].mean(),
                        'std': df[column].std(),
                        'min': df[column].min(),
                        'max': df[column].max(),
                        'median': df[column].median()
                    })
                
                # 文字列列の場合
                elif pd.api.types.is_string_dtype(df[column]):
                    column_stats.update({
                        'max_length': df[column].astype(str).str.len().max(),
                        'min_length': df[column].astype(str).str.len().min(),
                        'most_common': df[column].mode().iloc[0] if not df[column].mode().empty else None
                    })
                
                stats[column] = column_stats
            
            return stats
            
        except Exception as e:
            self.logger.error(f"統計情報取得失敗: {e}")
            return {}


# グローバルインスタンス
csv_io = CSVIO()

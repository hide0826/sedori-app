#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ルートサマリーテンプレート生成ユーティリティ

ルートサマリー入力用のCSV/Excelテンプレートを生成
"""

import pandas as pd
from pathlib import Path
from typing import List, Optional
from datetime import datetime
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


class TemplateGenerator:
    """ルートサマリーテンプレート生成クラス"""
    
    @staticmethod
    def generate_csv_template(output_path: str, route_code: Optional[str] = None, store_codes: Optional[List[str]] = None) -> bool:
        """
        CSV形式のルートサマリーテンプレートを生成
        
        Args:
            output_path: 出力ファイルパス
            route_code: ルートコード（任意）
            store_codes: 店舗コードリスト（任意）
        
        Returns:
            生成成功時True
        """
        try:
            # ルート情報セクションのデータ
            route_data = {
                '項目': [
                    'ルート日付',
                    'ルートコード',
                    '出発時間',
                    '帰宅時間',
                    '往路高速代',
                    '復路高速代',
                    '駐車場代',
                    '食費',
                    'その他経費',
                    '備考（天候等）'
                ],
                '値': [
                    datetime.now().strftime('%Y-%m-%d'),
                    route_code or '',
                    '',
                    '',
                    '',
                    '',
                    '',
                    '',
                    '',
                    ''
                ]
            }
            
            # 店舗訪問詳細セクションのヘッダー
            visit_headers = [
                '訪問順序',
                '店舗コード',
                '店舗IN時間',
                '店舗OUT時間',
                '前店舗からの移動時間（分）',
                '前店舗からの距離（km）',
                '店舗毎想定粗利',
                '店舗毎仕入れ点数',
                '仕入れ成功',
                '空振り理由',
                '店舗評価（1-5）',
                '店舗メモ',
                '次回訪問推奨度',
                '在庫状況',
                '競合いたか',
                'トラブルあったか',
                'トラブル詳細'
            ]
            
            # 店舗訪問詳細の初期データ
            visit_rows = []
            if store_codes:
                for i, store_code in enumerate(store_codes, 1):
                    visit_rows.append([
                        i,  # 訪問順序
                        store_code,
                        '',  # 店舗IN時間
                        '',  # 店舗OUT時間
                        '',  # 移動時間
                        '',  # 距離
                        '',  # 想定粗利
                        '',  # 仕入れ点数
                        'YES',  # 仕入れ成功（デフォルト）
                        '',  # 空振り理由
                        '',  # 店舗評価
                        '',  # 店舗メモ
                        '',  # 次回訪問推奨度
                        '',  # 在庫状況
                        'NO',  # 競合
                        'NO',  # トラブル
                        ''  # トラブル詳細
                    ])
            else:
                # 店舗コードが指定されていない場合は空の行を5行追加
                for i in range(1, 6):
                    visit_rows.append([
                        i,
                        '',
                        '',
                        '',
                        '',
                        '',
                        '',
                        '',
                        'YES',
                        '',
                        '',
                        '',
                        '',
                        '',
                        'NO',
                        'NO',
                        ''
                    ])
            
            # CSV形式で出力
            output_lines = []
            
            # ルート情報セクション
            output_lines.append('# === ルート情報 ===')
            output_lines.append(','.join(route_data['項目']))
            output_lines.append(','.join(str(v) for v in route_data['値']))
            output_lines.append('')
            
            # 店舗訪問詳細セクション
            output_lines.append('# === 店舗訪問詳細 ===')
            output_lines.append(','.join(visit_headers))
            for row in visit_rows:
                output_lines.append(','.join(str(v) for v in row))
            
            # ファイルに書き込み（UTF-8 BOM付き）
            with open(output_path, 'w', encoding='utf-8-sig', newline='') as f:
                f.write('\n'.join(output_lines))
            
            return True
            
        except Exception as e:
            print(f"CSVテンプレート生成エラー: {e}")
            return False
    
    @staticmethod
    def generate_excel_template(output_path: str, route_code: Optional[str] = None, store_codes: Optional[List[str]] = None) -> bool:
        """
        Excel形式のルートサマリーテンプレートを生成
        
        Args:
            output_path: 出力ファイルパス
            route_code: ルートコード（任意）
            store_codes: 店舗コードリスト（任意）
        
        Returns:
            生成成功時True
        """
        try:
            # ワークブック作成
            wb = openpyxl.Workbook()
            
            # デフォルトシートを削除
            if 'Sheet' in wb.sheetnames:
                wb.remove(wb['Sheet'])
            
            # === ルート情報シート ===
            route_sheet = wb.create_sheet('ルート情報', 0)
            
            # スタイル定義
            header_fill = PatternFill(start_color='366092', end_color='366092', fill_type='solid')
            header_font = Font(bold=True, color='FFFFFF')
            border = Border(
                left=Side(style='thin'),
                right=Side(style='thin'),
                top=Side(style='thin'),
                bottom=Side(style='thin')
            )
            
            # ルート情報ヘッダー
            route_sheet['A1'] = '項目'
            route_sheet['B1'] = '値'
            route_sheet['A1'].fill = header_fill
            route_sheet['A1'].font = header_font
            route_sheet['B1'].fill = header_fill
            route_sheet['B1'].font = header_font
            route_sheet['A1'].border = border
            route_sheet['B1'].border = border
            
            # ルート情報データ
            route_items = [
                ('ルート日付', datetime.now().strftime('%Y-%m-%d')),
                ('ルートコード', route_code or ''),
                ('出発時間', ''),
                ('帰宅時間', ''),
                ('往路高速代', ''),
                ('復路高速代', ''),
                ('駐車場代', ''),
                ('食費', ''),
                ('その他経費', ''),
                ('備考（天候等）', '')
            ]
            
            for row_idx, (item, value) in enumerate(route_items, start=2):
                route_sheet[f'A{row_idx}'] = item
                route_sheet[f'B{row_idx}'] = value
                route_sheet[f'A{row_idx}'].border = border
                route_sheet[f'B{row_idx}'].border = border
                route_sheet[f'A{row_idx}'].alignment = Alignment(vertical='center')
            
            # 列幅調整
            route_sheet.column_dimensions['A'].width = 20
            route_sheet.column_dimensions['B'].width = 25
            
            # === 店舗訪問詳細シート ===
            visit_sheet = wb.create_sheet('店舗訪問詳細', 1)
            
            # ヘッダー
            visit_headers = [
                '訪問順序',
                '店舗コード',
                '店舗IN時間',
                '店舗OUT時間',
                '前店舗からの移動時間（分）',
                '前店舗からの距離（km）',
                '店舗毎想定粗利',
                '店舗毎仕入れ点数',
                '仕入れ成功',
                '空振り理由',
                '店舗評価（1-5）',
                '店舗メモ',
                '次回訪問推奨度',
                '在庫状況',
                '競合いたか',
                'トラブルあったか',
                'トラブル詳細'
            ]
            
            for col_idx, header in enumerate(visit_headers, start=1):
                cell = visit_sheet.cell(row=1, column=col_idx)
                cell.value = header
                cell.fill = header_fill
                cell.font = header_font
                cell.border = border
                cell.alignment = Alignment(horizontal='center', vertical='center')
            
            # データ行
            visit_data_rows = []
            if store_codes:
                for i, store_code in enumerate(store_codes, 1):
                    visit_data_rows.append([
                        i,  # 訪問順序
                        store_code,
                        '',  # 店舗IN時間
                        '',  # 店舗OUT時間
                        '',  # 移動時間
                        '',  # 距離
                        '',  # 想定粗利
                        '',  # 仕入れ点数
                        'YES',  # 仕入れ成功
                        '',  # 空振り理由
                        '',  # 店舗評価
                        '',  # 店舗メモ
                        '',  # 次回訪問推奨度
                        '',  # 在庫状況
                        'NO',  # 競合
                        'NO',  # トラブル
                        ''  # トラブル詳細
                    ])
            else:
                # 空の行を5行追加
                for i in range(1, 6):
                    visit_data_rows.append([
                        i,
                        '',
                        '',
                        '',
                        '',
                        '',
                        '',
                        '',
                        'YES',
                        '',
                        '',
                        '',
                        '',
                        '',
                        'NO',
                        'NO',
                        ''
                    ])
            
            for row_idx, row_data in enumerate(visit_data_rows, start=2):
                for col_idx, value in enumerate(row_data, start=1):
                    cell = visit_sheet.cell(row=row_idx, column=col_idx)
                    cell.value = value
                    cell.border = border
                    if col_idx == 1:  # 訪問順序は中央揃え
                        cell.alignment = Alignment(horizontal='center', vertical='center')
            
            # 列幅調整
            column_widths = [10, 15, 18, 18, 20, 20, 18, 18, 12, 15, 12, 25, 18, 15, 12, 15, 25]
            for col_idx, width in enumerate(column_widths, start=1):
                visit_sheet.column_dimensions[get_column_letter(col_idx)].width = width
            
            # 1行目を固定
            visit_sheet.freeze_panes = 'A2'
            
            # 保存
            wb.save(output_path)
            return True
            
        except Exception as e:
            print(f"Excelテンプレート生成エラー: {e}")
            return False


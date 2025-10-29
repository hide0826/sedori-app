# HIRIOプロジェクト引き継ぎプロンプト（ルートサマリー機能実装完了時点）

## 📋 プロジェクト概要
- **目標**: 中古せどり業務自動化システム（PWAからPySide6デスクトップアプリ移行）
- **技術スタック**: PySide6 + FastAPI + SQLite
- **現在フェーズ**: Phase 1（仕入管理システム実装）
- **進捗状況**: 価格改定機能完了、仕入管理システム実装中、店舗マスタDB実装完了、**ルートサマリー機能実装完了**

## ✅ 完了済み機能

### 1. 価格改定機能（完全実装済み・本番稼働中・保護対象）
**ファイル**: `python/desktop/ui/repricer_widget.py`
- ✅ CSVファイル選択（設定のデフォルトディレクトリ対応）
- ✅ CSV内容自動プレビュー
- ✅ 価格改定プレビュー・実行
- ✅ 結果のCSV保存（変更のないSKUは除外）
- ✅ 数値ソート機能
- ✅ Trace変更の日本語表示
- ✅ Excel数式記法の自動クリーンアップ
- ✅ プライスター対応: Shift-JISエンコーディング、クォートなし形式
- ✅ 文字化け対策: 全角文字の自動置換処理

### 2. 価格改定ルール設定
**ファイル**: `python/desktop/ui/repricer_settings_widget.py`
- ✅ 1-360日の既存ルール
- ✅ 361日～の新規ルール追加
- ✅ アクション・priceTrace設定
- ✅ 設定の保存・読み込み

### 3. 仕入管理システム
**ファイル**: `python/desktop/ui/inventory_widget.py`
- ✅ CSV取込機能: 複数エンコーディング対応
- ✅ データプレビュー: 15列テーブル表示
- ✅ 検索・フィルタ機能
- ✅ SKU生成機能: APIクライアント連携、**店舗マスタ連携実装済み**
- ✅ 出力機能: CSV出力、出品CSV生成、古物台帳生成
- ✅ **SKU生成時に店舗マスタから仕入れ先コードを自動取得**

### 4. 店舗マスタDB作成・管理機能（2025-01-28完了）
**ファイル**: `python/desktop/ui/store_master_widget.py`, `python/desktop/database/store_db.py`
- ✅ データベース設計・作成
- ✅ Excelインポート機能
- ✅ 店舗マスタ管理画面（追加・編集・削除・検索）
- ✅ カスタムフィールド管理機能
- ✅ **ルート名選択・自動コード生成機能**（2025-01-28後半実装）
  - 所属ルート名: 編集可能なQComboBoxで既存ルート選択可
  - 既存ルート選択時にルートコード自動挿入
  - 既存ルート選択時に仕入れ先コード自動生成（末尾+1）
- ✅ **訪問順序保存機能**（2025-01-28後半実装）
  - `display_order`カラムを追加（マイグレーション対応）
  - 訪問順序の保存・読み込み機能

### 5. ルートサマリー機能・分析機能・エクスポート機能（2025-01-28実装完了）
**主要ファイル**:
- `python/desktop/database/route_db.py`: データベース操作
- `python/desktop/ui/route_summary_widget.py`: ルートサマリー入力画面（**統合版実装済み**）
- `python/desktop/ui/analysis_widget.py`: 分析画面
- `python/desktop/utils/template_generator.py`: テンプレート生成（**単一シート形式対応**）
- `python/desktop/utils/data_exporter.py`: データエクスポート
- `python/desktop/services/route_matching_service.py`: 照合処理
- `python/desktop/services/calculation_service.py`: 計算処理
- `python/desktop/ui/star_rating_widget.py`: 星評価ウィジェット（**新規追加**）

**実装内容**:
- ✅ データベース設計: route_summaries, store_visit_details テーブル
- ✅ **テンプレート生成機能: 単一シート形式（Excel）**
  - 店舗コード・店舗名・到着時刻・出発時刻・滞在時間・日付・備考を含む
  - ルート情報シートは削除（単一シート構成）
- ✅ **ルートコードプルダウン表示**: 店舗マスタから既存ルート名を取得して表示
- ✅ **選択ルートに基づくテンプレート生成**: 選択されたルートの店舗を自動でテンプレートに含める
- ✅ **店舗自動追加機能**: 重複チェック付きで店舗を一括追加
- ✅ **ルートサマリー入力画面: 統合版**
  - ルート情報と店舗訪問詳細を1つの画面に統合
  - 経費欄: 往路高速代・復路高速代のみ（駐車場代・食費・その他経費を削除）
- ✅ **ドラッグ＆ドロップ機能**: 訪問順序をドラッグ＆ドロップで変更可能
- ✅ **訪問順序の保存・読み込み**: 次回同ルート選択時に保存された順序で表示
- ✅ **Undo/Redo機能**: Ctrl+Z/Ctrl+Yで操作を元に戻す・やり直す
- ✅ **星評価ウィジェット**: 5段階評価（クリックで設定、同じ星を再クリックで0にリセット）
- ✅ **テーブル列の最適化**:
  - 追加: 店舗滞在時間
  - 削除: 距離（km）、仕入れ成功、空振り理由
  - 店舗名の列幅自動調整
- ✅ 照合処理: 仕入リストと店舗マスタの自動照合（時間・粗利ベース）
- ✅ 計算処理: 滞在時間、実働時間、時給、仕入れ成功率等
- ✅ 基本分析機能: 統計情報表示・グラフ分析（matplotlib）
- ✅ データエクスポート機能: CSV/Excel/Looker Studio用フォーマット
- ✅ Looker Studio連携手順書: `docs/looker_studio_guide.md`

## 📂 ファイル構成
```
python/desktop/
├── main.py                          # エントリーポイント
├── data/
│   └── hirio.db                    # SQLiteデータベース（自動生成）
├── database/
│   ├── __init__.py
│   ├── store_db.py                 # 店舗マスタDB操作（display_orderカラム追加済み）
│   └── route_db.py                 # ルートサマリーDB操作（新規）
├── api/
│   └── client.py                   # APIクライアント
├── services/
│   ├── route_matching_service.py   # 照合処理（新規）
│   └── calculation_service.py      # 計算処理（新規）
├── ui/
│   ├── main_window.py              # メインウィンドウ（ルートサマリー・分析タブ追加済み）
│   ├── repricer_widget.py          # 価格改定ウィジェット（完成・保護対象）
│   ├── repricer_settings_widget.py # 価格改定ルール設定（完成・保護対象）
│   ├── inventory_widget.py         # 仕入管理ウィジェット（店舗マスタ連携済み）
│   ├── store_master_widget.py      # 店舗マスタ管理（ルート名選択機能追加済み）
│   ├── route_summary_widget.py     # ルートサマリー入力（統合版実装済み）
│   ├── star_rating_widget.py      # 星評価ウィジェット（新規追加）
│   ├── analysis_widget.py          # 分析画面（新規）
│   ├── custom_fields_dialog.py     # カスタムフィールド管理
│   └── settings_widget.py          # 設定ウィジェット
└── utils/
    ├── template_generator.py       # テンプレート生成（単一シート形式対応）
    ├── data_exporter.py           # データエクスポート（新規）
    ├── excel_importer.py           # Excelインポート
    └── csv_io.py                   # CSV I/O

docs/
├── cursor_development_progress.md  # 開発進捗記録（最新更新: 2025-01-28）
├── looker_studio_guide.md          # Looker Studio連携手順書（新規）
└── handover_prompt_route_summary.md  # 引き継ぎプロンプト（本ファイル）
```

## 🗄️ データベース構造

### stores テーブル
```sql
CREATE TABLE stores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    affiliated_route_name TEXT,
    route_code TEXT,
    supplier_code TEXT UNIQUE,
    store_name TEXT NOT NULL,
    custom_fields TEXT,  -- JSON形式
    display_order INTEGER DEFAULT 0,  -- 訪問順序（追加）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### store_custom_fields テーブル
```sql
CREATE TABLE store_custom_fields (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    field_name TEXT UNIQUE NOT NULL,
    field_type TEXT NOT NULL,  -- TEXT, INTEGER, REAL, DATE
    display_name TEXT NOT NULL,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### route_summaries テーブル
```sql
CREATE TABLE route_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    route_date DATE NOT NULL,
    route_code TEXT NOT NULL,
    departure_time DATETIME,
    return_time DATETIME,
    toll_fee_outbound REAL,
    toll_fee_return REAL,
    parking_fee REAL,  -- 削除予定（現在は0で保存）
    meal_cost REAL,  -- 削除予定（現在は0で保存）
    other_expenses REAL,  -- 削除予定（現在は0で保存）
    remarks TEXT,
    total_working_hours REAL,
    estimated_hourly_rate REAL,
    total_gross_profit REAL,
    purchase_success_rate REAL,
    avg_purchase_price REAL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### store_visit_details テーブル
```sql
CREATE TABLE store_visit_details (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    route_summary_id INTEGER,
    store_code TEXT NOT NULL,
    visit_order INTEGER,
    store_in_time DATETIME,
    store_out_time DATETIME,
    stay_duration REAL,  -- 店舗滞在時間
    travel_time_from_prev REAL,
    distance_from_prev REAL,  -- 削除予定
    store_gross_profit REAL,
    store_item_count INTEGER,
    purchase_success INTEGER DEFAULT 0,  -- 削除予定
    no_purchase_reason TEXT,  -- 削除予定
    store_rating INTEGER,  -- 星評価（0-5）
    store_notes TEXT,
    next_visit_recommendation TEXT,
    category_breakdown TEXT,  -- JSON形式
    competitor_present INTEGER DEFAULT 0,
    inventory_level TEXT,
    trouble_occurred INTEGER DEFAULT 0,
    trouble_details TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (route_summary_id) REFERENCES route_summaries(id) ON DELETE CASCADE
);
```

## 🎯 動作確認済み項目

### 店舗マスタ機能
- ✅ Excelインポート: Excelファイルからインポート成功
- ✅ 店舗追加・編集・削除: 正常動作
- ✅ ソート機能: 全列でソート可能
- ✅ カスタムフィールド追加: 正常動作
- ✅ **ルート名選択: 既存ルートから選択可**
- ✅ **ルートコード自動挿入: 既存ルート選択時に自動**
- ✅ **仕入れ先コード自動生成: 既存ルート選択時に末尾+1**
- ✅ **訪問順序の保存・読み込み: 正常動作**

### ルートサマリー機能
- ✅ **ルートコードプルダウン表示: 正常動作**
- ✅ **テンプレート生成: 単一シート形式で正常動作**
- ✅ **店舗自動追加: 重複チェック付きで正常動作**
- ✅ **ドラッグ＆ドロップ: 訪問順序変更可能**
- ✅ **訪問順序の保存: データベースに正常保存**
- ✅ **Undo/Redo機能: Ctrl+Z/Ctrl+Yで正常動作**
- ✅ **星評価ウィジェット: クリックで評価設定可能**
- ✅ **タブ統合: ルート情報と店舗訪問詳細が1画面に統合**
- ✅ **経費欄簡素化: 駐車場代・食費・その他経費が削除済み**

### SKU生成機能との連携
- ✅ 店舗マスタから仕入れ先コード取得機能
- ✅ SKU生成時に店舗情報を付与
- ✅ 店舗未登録時の警告表示

## 🚨 重要注意事項

### 1. 既存機能保護（最優先）
- **価格改定機能は完全に保護**: 本番稼働中、絶対に壊さないこと
- **修正前のバックアップ作成**: 必須
- **段階的実装**: 1工程ずつ動作確認してから次へ

### 2. データベース
- **初回起動時に自動生成**: `python/desktop/data/hirio.db`
- **カスタムフィールド**: JSON形式で保存
- **仕入れ先コード**: UNIQUE制約あり、重複チェック機能あり
- **訪問順序**: `display_order`カラムが自動マイグレーションで追加される

### 3. ルートサマリー機能の現在の状態
- ✅ 基本機能: 実装完了・動作確認済み
- ✅ テンプレート生成: 単一シート形式で動作確認済み
- ✅ 店舗訪問詳細: 統合版で動作確認済み
- ⚠️ 計算処理: 一部エラーが発生する可能性あり（`calculate_route_statistics`がNoneの場合）

## 🔄 実装中・未実装機能

### ⚠️ 一部実装・動作確認待ち
- 照合処理（実装済み、精度向上の余地あり）
- 分析機能グラフ表示（matplotlib使用、動作確認必要）

### ❌ 未実装
- バックエンドAPIの完全実装（一部ダミー実装あり）
- 作業フローの実際の動作連携
- 検品リスト作成機能
- 外注用リスト作成機能
- 古物台帳作成機能（後回し）

## 🎯 次の実装タスク（優先度順）

### 1. バグ修正・動作確認（優先度最高）
**対象**: ルートサマリー機能全般
- [ ] 計算処理のエラー修正（`calculate_route_statistics`がNoneの場合のエラーハンドリング）
- [ ] テンプレート読み込み時の列マッピング確認
- [ ] データ保存時の訪問順序保存確認

### 2. 分析機能のグラフ表示実装（優先度高）
**対象ファイル**: `python/desktop/ui/analysis_widget.py`
- [ ] 店舗別粗利ランキンググラフの実装
- [ ] ルート別時給比較グラフの実装
- [ ] 月別仕入れ数推移グラフの実装
- [ ] 店舗評価推移グラフの実装

### 3. 照合処理の精度向上（優先度中）
**対象ファイル**: `python/desktop/services/route_matching_service.py`
- [ ] 照合スコア計算ロジックの調整
- [ ] 照合失敗時の手動修正UI
- [ ] 複数候補表示機能

## 📝 開発環境の起動方法

### 1. バックエンド起動
```bash
cd python
python app.py
```

### 2. デスクトップアプリ起動
```bash
cd python/desktop
python main.py
```

## 💡 開発時の心構え

1. **既存機能保護を最優先**: 価格改定機能は絶対に壊さない
2. **段階的実装**: 1つずつ動作確認しながら進める
3. **エラーハンドリング**: 常にフォールバック機能を用意
4. **UI/UX改善**: ユーザーが使いやすいことを最優先に
5. **データベース整合性**: 仕入れ先コードの一意性を保つ

## 📚 参照ファイル
- `docs/cursor_development_progress.md`: 詳細な開発進捗記録
- `docs/looker_studio_guide.md`: Looker Studio連携手順書
- `docs/pyside6_desktop_app_specification.md`: プロジェクト仕様（参照のこと）

## 🔧 最新の実装詳細（2025-01-28時点）

### ルートサマリー機能の主な特徴
1. **統合UI**: ルート情報と店舗訪問詳細を1画面に統合
2. **ルートコードプルダウン**: 店舗マスタから既存ルート名を取得して表示
3. **テンプレート生成**: 選択されたルートの店舗を含む単一シートExcelテンプレートを生成
4. **店舗自動追加**: 重複チェック付きで店舗を一括追加
5. **ドラッグ＆ドロップ**: 訪問順序をドラッグ＆ドロップで変更可能
6. **訪問順序保存**: 次回同ルート選択時に保存された順序で表示
7. **Undo/Redo**: Ctrl+Z/Ctrl+Yで操作を元に戻す・やり直す
8. **星評価**: 5段階評価ウィジェット（クリックで設定）
9. **経費欄簡素化**: 往路高速代・復路高速代のみ表示

### テーブル列構成（店舗訪問詳細）
1. 訪問順序
2. 店舗コード
3. 店舗名（列幅自動調整）
4. 店舗IN時間
5. 店舗OUT時間
6. 店舗滞在時間（新規追加）
7. 移動時間（分）
8. 想定粗利
9. 仕入れ点数
10. 店舗評価（星評価ウィジェット）
11. 店舗メモ

### 削除された列
- 距離（km）
- 仕入れ成功
- 空振り理由

### 削除された経費項目
- 駐車場代
- 食費
- その他経費

---

**引き継ぎ日**: 2025年1月28日  
**現在の進捗**: ルートサマリー機能実装完了（統合UI、星評価、Undo/Redo機能含む）  
**次フェーズ**: バグ修正・動作確認、分析機能のグラフ表示実装


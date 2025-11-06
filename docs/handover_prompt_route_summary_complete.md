# HIRIO デスクトップアプリ 引き継ぎプロンプト（ルート機能完成版）

## 目的
- PySide6 + FastAPI + SQLite のローカルデスクトップアプリ
- フェーズ: ルート登録・ルートサマリー機能の完成・運用
- 本プロンプトは、次チャットでエージェントが即座に継続作業できるようにする引き継ぎ資料

## リポジトリ/環境
- OS: Windows 10/11（Python 3.11 目安）
- ルート: `D:\HIRIO\repo\sedori-app.github`
- 仮想環境（任意）: venv/conda 推奨
- 依存: `python/requirements.txt`

## 起動手順
1) FastAPI（任意: アプリ内からも起動可）
- 手動起動: `cd python && python app.py`（デフォルト: http://localhost:8000）

2) デスクトップアプリ
- `cd python/desktop`
- `python main.py`

## 構成（主要ファイル）
- デスクトップ UI:
  - `python/desktop/ui/main_window.py`
  - `python/desktop/ui/route_summary_widget.py`（ルート登録画面）
  - `python/desktop/ui/route_list_widget.py`（ルートサマリー一覧画面）⭐ 新規
  - `python/desktop/ui/inventory_widget.py`（仕入管理、保存機能追加）⭐ 拡張
  - `python/desktop/ui/store_master_widget.py`（店舗マスタ）
  - `python/desktop/ui/star_rating_widget.py`（星評価）
  - `python/desktop/ui/styles.qss`（全体スタイル）
- DB アクセス:
  - `python/desktop/database/route_db.py`
  - `python/desktop/database/store_db.py`
  - `python/desktop/database/inventory_db.py`（仕入データ保存）⭐ 新規
- サービス:
  - `python/desktop/services/route_matching_service.py`（照合処理）
  - `python/desktop/services/calculation_service.py`（計算）
  - `python/services/inventory_service.py`（仕入CSV処理、SKU生成、出品CSV生成）
  - `python/services/sku_template.py`（SKUテンプレートレンダラ）⭐ 新規
- API クライアント:
  - `python/desktop/api/client.py`
- バックエンド API:
  - `python/routers/inventory.py`（SKU生成、出品CSV生成、照合処理API）⭐ 拡張
  - `python/utils/csv_io.py`（CSV I/Oエンジン）
  - `python/app.py`（inventory_router有効化済み）
- 設定ファイル:
  - `config/inventory_settings.json`（SKUテンプレート設定）⭐ 新規

## 現行仕様（ルート登録）

**注意:** タブ名は「ルートサマリー」から「ルート登録」に変更されました（2025-02-01）

### ルート情報
- ルート日付（カレンダー）
- ルートコード（プルダウン、編集可）
- 出発時間・帰宅時間: `QLineEdit`（`HH:MM`形式、自由入力）
  - 保存時は「ルート日付 + HH:MM:00」で結合
- 経費: 往路/復路高速代（整数・円表示）
- 備考

### 店舗訪問詳細
- 列: 訪問順序/店舗コード/店舗名/IN/OUT/滞在時間/移動時間/想定粗利/仕入点数/評価/メモ
- **自動計算:**
  - 滞在時間（分）= OUT時間 - IN時間
  - 移動時間（分）: 1店舗目=出発→IN、2店舗目以降=前OUT→現在IN
- ドラッグ＆ドロップで順序変更（列ズレ対策済み）
- 星評価はセル内ウィジェット
- メモは選択枠の過度な強調を抑制（入力中は視認性向上）

### 操作ボタン
- **テンプレート生成/読み込み**
- **照合処理実行** ⭐ 新機能
  - 仕入管理タブのデータを参照 → 時間許容誤差入力 → ルートの店舗IN/OUTと照合
  - マッチした行の「仕入先」列に店舗コードを自動付与 → 仕入管理タブに自動反映
  - 想定粗利・仕入れ点数を自動計算
  - API: `POST /api/inventory/match-stores-from-data`
  - 仕入管理にデータがない場合はCSVファイル選択にフォールバック
- **照合再計算** ⭐ 新機能
  - 仕入管理タブのデータから想定粗利・仕入れ点数を再計算
  - 店舗コードのみを参照（時間照合なし）
  - 価格変更・仕入れ点数変更の反映用
- **選択ルートの店舗を自動追加**（重複除外・順序自動付与）
- **保存** ⭐ 計算サービス未初期化でも保存可能
- **保存履歴** ⭐ 新機能
  - 日付・ルート名で検索可能（デフォルトは全件表示）
  - 一覧から読み込み/削除を実行
  - 読み込み時はルートコードを日本語名で表示
- **新規作成**
- **行追加/行削除/全行クリア**（確認ダイアログあり）
- **Undo/Redo**（Ctrl+Z/Ctrl+Y）

### 店舗マスタから追加
- 「店舗追加（店舗マスタから）」ボタン
- 検索＋複数選択 → 一括挿入

## 現行仕様（仕入管理）⭐ 拡張

### 仕入データ保存機能
- **保存:** 現在の仕入データをスナップショットとして保存
- **保存名自動生成:** `yyyy/mm/dd ○○ルート` 形式
  - 仕入れ日（CSVデータから取得）
  - ルート名（ルート登録タブから取得）
  - ダイアログで「この名称で保存してよろしいですか？\n編集も可能です」と表示
- **保存履歴:**
  - 保存名・件数・作成日時を一覧表示
  - 検索機能（保存名で絞り込み）
  - 読み込み/削除を実行
- **10件制限:**
  - 10件を超える場合は古いデータを自動削除
- **データベース:** `inventory_snapshots` テーブル

### SKU生成機能
- **SKUテンプレート:** 設定ファイルでカスタマイズ可能
- **デスクトップ設定パネル:**
  - 8スロット式ビルダー
  - テンプレート保存/読み込み
- **反映ロジック:** ASIN→JAN→商品名→未実装行の順

### 出品CSV生成機能
- **フォーマット:** 指定ファイルに完全準拠
- **エンコーディング:** Shift-JIS (cp932)
- **1行目:** 注意文
- **コンディション:** Amazon形式にマッピング（中古(良い)→"3"など）
- **ASIN/JAN:** 相互排他処理

## 現行仕様（ルートサマリー一覧）⭐ 新規

### ルートサマリー一覧タブ
- **表示項目:**
  - 日付
  - ルート名（ルートコードから自動変換）
  - 総仕入点数（全店舗の仕入点数合計）
  - 総想定粗利（全店舗の想定粗利合計）
  - 平均仕入価格
  - 総稼働時間
  - 想定時給
- **機能:**
  - ソート機能（全カラム対応）
  - 更新ボタンで手動リフレッシュ
  - ダブルクリックで詳細表示（実装予定）
  - 統計情報表示（ルート数）

### 店舗マスタタブ ⭐ 新規機能

#### ルート選択機能
- **一行プルダウン形式:** ルート名（ルートコード）- 店舗数店舗
- **操作ボタン:**
  - ルート呼び出し: 選択したルートの店舗のみ表示
  - ルート解除: 全店舗表示に戻る
- **Google Map URL管理:**
  - URL入力・保存・ブラウザで開く
  - ルート選択でURLを自動表示
  - 保存時にデータベースに自動保存

#### 店舗一覧フィルタリング
- ルート呼び出し時、該当ルートの店舗のみ表示
- 検索フィールドでさらに絞り込み可能
- 解除ボタンで全店舗表示に戻る

#### データベース拡張
- `routes` テーブル追加（ルート名・ルートコード・Google Map URL管理）
- `stores` テーブルに `google_map_url` カラム追加

## 直近の実装内容（重要）

### 1. 行操作機能の修正
- **問題:** 行追加・削除・全行クリアが機能しない
- **原因:** メソッドが `StoreSelectDialog` クラス内に誤配置
- **対応:** `RouteSummaryWidget` 内に正しく移動、直接シグナル接続に変更

### 2. 保存/読み込み/削除機能
- **保存:** ルート情報＋店舗訪問詳細をDBに保存（計算サービス未初期化でも可）
- **保存履歴ダイアログ:**
  - 日付・ルート名で検索（チェックボックス式、デフォルトは全件）
  - 一覧から選択して読み込み/削除
- **読み込み:** 店舗名は店舗マスタから自動補完（`supplier_code` → `store_name`）

### 3. 自動計算機能
- **滞在時間:** OUT時間 - IN時間（分）
- **移動時間:** 出発→1店舗目IN、前店舗OUT→現在IN（分）
- IN/OUT時刻入力後に自動再計算

### 4. 照合処理API実装（改良版・二重実装）
- **エンドポイントA:** `POST /api/inventory/match-stores`（CSVファイル版）
  - CSVファイルを選択して照合
  - プレビュー表示（先頭10件）
- **エンドポイントB:** `POST /api/inventory/match-stores-from-data`（JSONデータ版）⭐ 新規
  - 仕入管理タブのデータを直接参照
  - 全データを返却
  - NaN値処理: 送信側/受信側で処理
  - 時間フォーマット修正: DBのHH:MM形式に日付を結合
- **入力:** `route_summary_id`、`time_tolerance_minutes`（デフォルト30）
- **処理:**
  - CSV/JSON読み込み・正規化（`InventoryService.process_inventory_csv`）
  - 仕入日時カラム自動推定（仕入れ日、purchaseDate、purchase_date）
  - 仕入先カラム自動作成（存在しない場合）
  - ルート訪問詳細取得（`RouteDatabase.get_store_visits_by_route`）
  - ルート日付を店舗IN/OUT時間に結合（HH:MM形式の既存データ対応）
  - 時間照合（`RouteMatchingService.match_store_code_by_time_and_profit`）
  - マッチした行の「仕入先」列に店舗コードを自動付与
  - 照合後、店舗コード別の粗利を集計してルートサマリーを自動更新
- **UI:** ルートサマリーの「照合処理実行」ボタンから実行

### 5. 照合再計算機能 ⭐ 新規（2025-02-01 改良版）
- **ボタン:** 「照合再計算」（行追加・行削除・全行クリアの横）
- **機能:** 仕入管理タブのデータから想定粗利・仕入れ点数を再計算
- **処理:**
  - **重要:** テーブルから最新データを再取得（手入力商品を含む）
  - `inventory_widget.get_table_data()` でテーブルから直接データ取得
  - `inventory_widget.sync_inventory_data_from_table()` でデータ同期
  - 店舗コードのみを参照（時間照合なし）
  - 仕入管理の価格変更・仕入れ点数変更を反映
  - 他の項目（訪問順序、店舗コードなど）は変更しない
- **計算方法（2025-02-01 変更）:**
  - **想定粗利:** `仕入れ個数 × 見込み利益` を店舗別に合計
  - **仕入れ点数:** 店舗毎の「仕入れ個数」の総数（SUM）
- **UI:** 確認ダイアログ表示後、自動再計算

### 6. ルートコード日本語表示（2025-02-01 改良版）
- **読み込み時:** ルートコードを日本語名に自動変換
- **メソッド:** `store_db.get_route_name_by_code()` 追加
- **対応:** 保存履歴からの読み込み時に正しい日本語名を表示
- **改善点:**
  - シグナルブロック（`blockSignals(True)`）で `currentTextChanged` の発火を防止
  - デバッグログ追加（`route_code`、`route_name`、`display_value` を出力）
  - コンボボックス更新後にルート名を設定する処理を改善

### 7. 想定粗利・仕入れ点数表示改善（2025-02-01 計算方法変更）
- **想定粗利:** 整数表示（小数点なし）
  - **計算式:** `仕入れ個数 × 見込み利益` を店舗別に合計
  - 使用する列: `仕入れ個数`（7列目）、`見込み利益`（10列目）
- **仕入れ点数:** 整数表示
  - **計算式:** 店舗毎の「仕入れ個数」の総数（SUM）
  - 変更前は行数カウント、変更後は個数の合計
- **マッチしない店舗:** 0で統一（空白ではない）

### 8. その他の修正
- Undo/Redo改善（直前と同じ状態はスキップ、正しく復元）
- 列ズレ対策（`setSectionsMovable(False)`、`setAutoScroll(False)`）
- 例外ログ強化（`desktop_error.log` に自動保存）
- StoreMaster編集ボタンの選択取得修正

## 既知の課題 / 注意点
- 計算サービス（`CalculationService`）が初期化されていない環境では計算結果表示をスキップ（安全呼び出し）
- 出発/帰宅のテキストは簡易バリデーション（`HH:MM`）のみ
  - 不正値は保存時に `00:00:00` として扱う（強制エラーにはしない）
- 照合処理は「ルートを保存済み」である必要がある（`current_route_id` 必須）

## 操作メモ（よくあるポイント）
- **行削除:** 行を選択（行選択 or セル選択）→ 削除。選択が無いと警告
- **全行クリア:** 確認ダイアログ表示 → Yes で即時クリア
- **保存履歴:**
  - デフォルトは全履歴表示
  - 日付のみチェック → 該当日のみ
  - ルート名のみチェック → 該当ルートのみ
  - 両方チェック → 両条件で絞り込み
- **照合処理（改良版）:**
  1. ルートサマリーでルートを保存（必須）
  2. 仕入管理タブにデータを取り込み
  3. 「照合処理実行」ボタンクリック
  4. 時間許容誤差入力（デフォルト30分）
  5. 想定粗利・仕入れ点数が自動計算される
  6. 仕入管理タブの店舗コードも自動付与される
- **照合再計算:**
  1. 仕入管理タブで価格・仕入れ点数を変更
  2. 「照合再計算」ボタンクリック
  3. 想定粗利・仕入れ点数が自動再計算される

## 技術詳細

### API エンドポイント

**A. CSVファイル版**
```
POST /api/inventory/match-stores
Content-Type: multipart/form-data
- file: CSVファイル
- route_summary_id: int
- time_tolerance_minutes: int (デフォルト30)

レスポンス（プレビュー10件）:
{
  "status": "success",
  "stats": {"total_rows": 100, "matched_rows": 85, ...},
  "preview": [...]
}
```

**B. JSONデータ版** ⭐ 新規
```
POST /api/inventory/match-stores-from-data
Content-Type: application/json
{
  "purchase_data": [...],
  "route_summary_id": 1,
  "time_tolerance_minutes": 30
}

レスポンス（全データ）:
{
  "status": "success",
  "stats": {"total_rows": 100, "matched_rows": 85},
  "data": [...]  // 全データを返却
}
```

### データベース構造
- **データベースファイル:** `python/desktop/data/hirio.db`（SQLite3）
- **保存方式:** `RouteDatabase` / `StoreDatabase` / `InventoryDatabase` クラス経由でSQLiteに保存
  - 保存ボタンクリック時に自動保存
  - アプリ再起動後もデータは保持される
- **テーブル:**
  - `route_summaries`: ルート情報（日付、コード、出発/帰宅時間、経費、備考、計算結果、総仕入点数）
  - `store_visit_details`: 店舗訪問詳細（順序、コード、IN/OUT、滞在時間、移動時間、粗利、点数、評価、メモ）
    - 注意: `store_name` は保存されない（`store_code` のみ）
    - 読み込み時は店舗マスタから `supplier_code` → `store_name` を補完
  - `routes`: ルート情報管理（ルート名、ルートコード、Google Map URL）⭐ 新規
  - `stores`: 店舗情報（店舗マスタ）
    - `google_map_url` カラム追加 ⭐ 新規
  - `inventory_snapshots`: 仕入データスナップショット ⭐ 新規
    - 保存名、件数、データ（JSON形式）、作成/更新日時
    - 10件制限あり（超過時は自動削除）

## 次にやるべきこと（推奨）
1) 入力バリデーションの強化
   - 出発/帰宅 `HH:MM` 正規表現チェック＋エラーメッセージ
2) 照合結果の詳細表示
   - プレビューではなく、全データの確認・修正UI
   - CSVダウンロード機能
3) 計算サービスの初期化/依存解消
   - `update_calculation_results` を常時有効化
4) UI 細部
   - メモ列の入力視認性/行選択色の微調整（styles.qss）

## 連絡事項
- 価格改定系の既存機能は「壊さない」前提（保護対象）
- 変更は `styles.qss` を中心にUI統一、機能側は `route_summary_widget.py` に集約
- 何か落ちる場合は「起動ログの最後の AttributeError 名」または `desktop_error.log` の内容を最優先で共有

## Git状態
- **最新コミット（2025-02-01）:** `4df8ef8` - 仕入管理タブに保存機能追加
  - InventoryDatabaseクラス作成（inventory_snapshotsテーブル）
  - 10件制限＋古いデータ自動削除
  - 保存/読み込み/削除機能実装
  - 保存履歴ダイアログ追加
  - 保存名自動生成（yyyy/mm/dd ○○ルート形式）
- **最新の実装コミット:**
  - `30dd1e0` - 出品CSV生成機能実装完了
  - `af19794` - SKUテンプレート機能実装完了
  - `4df8ef8` - 仕入管理タブに保存機能追加
- **主要変更ファイル:**
  - `python/services/sku_template.py`（新規・SKUテンプレートレンダラ）
  - `python/services/inventory_service.py`（出品CSV生成、SKU生成改良）
  - `python/routers/inventory.py`（出品CSV生成API、SKUテンプレートAPI）
  - `python/utils/csv_io.py`（出品CSV形式修正）
  - `python/desktop/database/inventory_db.py`（新規・仕入データ保存）
  - `python/desktop/ui/inventory_widget.py`（保存機能・保存名自動生成）
  - `python/desktop/ui/main_window.py`（ルートサマリー参照追加）
  - `config/inventory_settings.json`（新規・SKU設定）
- **リモート:** `origin/main` にプッシュ済み

## 最新実装まとめ（2025-02-01 更新）
### ルート管理機能
1. ✅ 照合処理改良版（仕入管理データ参照、自動粗利計算）
2. ✅ 照合再計算機能改良（テーブルからデータ再取得、手入力商品対応）
3. ✅ 想定粗利計算方法変更（仕入れ個数 × 見込み利益）
4. ✅ 仕入れ点数計算方法変更（店舗毎の仕入れ個数の総数）
5. ✅ ルートコード日本語表示（シグナルブロック追加）
6. ✅ ルートサマリータブ名を「ルート登録」に変更
7. ✅ 想定粗利整数表示・マッチ0件を0に統一
8. ✅ NaN値問題修正
9. ✅ 時間フォーマット問題修正
10. ✅ ルートサマリー一覧タブ追加（総仕入点数・総想定粗利表示）
11. ✅ 店舗マスタにルート選択機能追加
12. ✅ Google Map URL管理機能追加
13. ✅ 総仕入点数自動計算・同期機能

### 仕入管理機能（2025-02-01 追加）
14. ✅ SKUテンプレート機能実装完了
15. ✅ 出品CSV生成機能実装完了
16. ✅ 仕入データ保存機能追加
    - InventoryDatabaseクラス作成
    - 10件制限＋古いデータ自動削除
    - 保存/読み込み/削除機能
    - 保存履歴ダイアログ
    - 保存名自動生成（yyyy/mm/dd ○○ルート形式）

## 直近の修正（2025-02-01）

### 仕入管理機能追加
1. ✅ SKUテンプレート機能実装完了
   - SKUテンプレートレンダラ作成
   - 設定ファイル管理
   - デスクトップ設定パネル追加
   - 一括SKU生成をテンプレート式に置換

2. ✅ 出品CSV生成機能実装完了
   - 指定フォーマットに完全準拠
   - Shift-JISエンコーディング対応
   - コンディションマッピング対応
   - ASIN/JAN相互排他処理

3. ✅ 仕入データ保存機能追加
   - InventoryDatabaseクラス作成
   - 10件制限＋古いデータ自動削除
   - 保存/読み込み/削除機能
   - 保存名自動生成（yyyy/mm/dd ○○ルート形式）

### ルート管理機能修正
4. ✅ 店舗IN/OUT時間表示修正
   - 問題: 保存履歴読み込み時に「2025-」と表示
   - 原因: 文字列の先頭5文字を切り取っていた
   - 修正: `split(' ')` で時間部分（HH:MM）を正しく抽出

5. ✅ 照合処理の修正（滞在時間内のみマッチ）
   - 問題: ±30分の許容範囲が広すぎて重複マッチ
   - 修正: 店舗IN/OUTの間のみマッチ（許容範囲なし）

6. ✅ 照合再計算で括弧付き店舗コード対応
   - 問題: 手入力の「(K1-010)」がマッチしない
   - 修正: 括弧を除去して正規化

7. ✅ 仕入れ価格0円の商品も粗利計算に含める
   - 問題: `if purchase_price and planned_price` で0円商品が除外
   - 修正: `if purchase_price is not None and planned_price is not None` に変更

8. ✅ 照合再計算にデバッグログ追加
   - K1-010の全データ一覧出力
   - 店舗別粗利集計結果出力
   - 更新処理の詳細ログ

## 過去の修正（2025-11-02）
1. ✅ ルートサマリー一覧タブの追加
   - 新しいタブ「ルートサマリー」を追加
   - 保存されたルート情報を一覧表示
   - 総仕入点数・総想定粗利・平均仕入価格・総稼働時間・想定時給を表示
   - ソート機能・統計情報表示

2. ✅ 総仕入点数の追加
   - `route_summaries` テーブルに `total_item_count` カラム追加
   - 保存時に店舗訪問詳細から総仕入点数を自動計算
   - 既存データの同期機能実装

3. ✅ 総想定粗利の自動計算
   - 保存時に店舗訪問詳細から総想定粗利を自動計算
   - 計算サービスの結果を上書きして実データを反映
   - 既存データの同期処理追加

4. ✅ 店舗マスタタブの機能拡張
   - ルート選択機能（一行プルダウン形式）
   - ルート呼び出し/解除ボタンで店舗一覧フィルタリング
   - Google Map URL管理（入力・保存・ブラウザで開く）
   - `routes` テーブル追加・`stores` テーブル拡張

## 解決済みの問題

**照合再計算で手入力商品が反映されない（2025-02-01 解決）**
- **問題:** テーブルで手入力した商品が照合再計算に反映されない
- **原因:** `inventory_data` がCSV取り込み時のデータのままで、テーブル編集が反映されていなかった
- **解決:** 照合再計算時に `get_table_data()` でテーブルから最新データを再取得する処理を追加

**ルートサマリー一覧に粗利・点数が反映されない（2025-11-02 解決）**
- **問題:** ルート登録には粗利・点数があるがルートサマリー一覧に反映されない
- **原因:** 既存データに `total_item_count` カラムがない、保存時に計算処理が不完全
- **解決:** 
  - `total_item_count` カラム追加とマイグレーション
  - 保存時に店舗訪問詳細から総仕入点数・総想定粗利を自動計算
  - 既存データの同期処理 `sync_total_item_count_from_visits()` を実装

## 技術的な注意点
- 照合処理の時間許容は廃止（滞在時間内のみ）
- 仕入れ価格0円は有効（粗利計算に含める）
- 括弧付き店舗コードは自動正規化
- `inventory_data` は DataFrame として扱う（`fillna('')` 後に `to_dict(orient="records")`）
- **照合再計算時:** テーブルから直接データを取得するため、手入力商品も反映される
- **データベース保存:** SQLite3（`python/desktop/data/hirio.db`）に保存される
- **inventory_widget の新メソッド:**
  - `get_table_data()`: テーブルから現在のデータを取得してDataFrameに変換
  - `sync_inventory_data_from_table()`: テーブルの内容をinventory_dataに同期
- **総仕入点数・総想定粗利:**
  - 保存時に店舗訪問詳細から自動集計
  - 既存データは初回表示時に自動同期
  - 計算サービスの結果は上書きされる（実データ優先）

## 次のタスク候補
- ルートサマリー一覧のダブルクリックでルート登録タブを開く機能
- ルートサマリー一覧のCSVエクスポート機能
- ルート別の集計・分析機能（店舗別成績など）
- 保存履歴のルートコード修正機能（誤って保存したルートコードを後から修正）
- 照合結果の詳細表示UI（プレビューではなく、全データの確認・修正）
- CSVダウンロード機能
- 入力バリデーション強化（出発/帰宅時間の正規表現チェック）
- UI磨き込み
- データベースのバックアップ・復元機能

---

以上。次チャットでは本プロンプトを貼り付けて「続きから」と伝えてください。


## Agentモード用プロンプト（このまま貼り付けてください）

```
今から「HIRIO デスクトップアプリ（PySide6）＋ FastAPI」の継続開発を行います。直近までの状況は下記の通りです。

[現状サマリ]
- 仕入管理/ルート登録/店舗マスタ/ルート一覧は稼働中。
- 照合処理API（CSV版・JSON版）実装済み。NaN・時間結合の正規化あり。
- SKUテンプレート機能実装完了（2025-02-01）。
  - レンダラ: `python/services/sku_template.py`
  - 設定: `config/inventory_settings.json`
  - 既存一括SKU生成はテンプレ式に置換（`InventoryService.generate_sku_bulk`）。
  - 設定API: GET/POST `/api/inventory/sku-template`。
  - デスクトップ側に設定パネル追加（仕入管理タブ内、トグル開閉・8スロット式ビルダー・保存/読込）。
  - SKU反映ロジック強化（ASIN→JAN→商品名→未実装行の順）。
- 出品CSV生成機能実装完了（2025-02-01）。
  - 指定フォーマットに完全準拠（Shift-JIS）。
  - コンディションマッピング対応。
  - ASIN/JAN相互排他処理。
- 仕入データ保存機能追加（2025-02-01）。
  - InventoryDatabaseクラス作成。
  - 10件制限＋古いデータ自動削除。
  - 保存名自動生成（yyyy/mm/dd ○○ルート形式）。
  - 保存履歴ダイアログ。

[開始時の確認]
1) API起動: `cd python && python app.py`（http://localhost:8000）。
2) デスクトップ起動: `cd python/desktop && python main.py`。
3) 設定画面で APIベースURL `http://localhost:8000` を確認し、接続テストOKであること。

[主なファイル]
- API: `python/routers/inventory.py`, `python/services/inventory_service.py`, `python/services/sku_template.py`
- CSV: `python/utils/csv_io.py`（出品CSV生成）
- DB: `python/desktop/database/inventory_db.py`（仕入データ保存）
- デスクトップ: `python/desktop/ui/inventory_widget.py`, `python/desktop/api/client.py`

[当面のタスク例]
1) SKUテンプレの正規化強化（商品名の全角/半角・連続空白・="…" の除去など）。
2) 未実装SKUが出ないか、サンプルCSVで再確認。問題あれば一致ロジック/ログ強化。
3) 仕入管理のエクスポート/プレビュー改善（任意）。
4) 古物台帳生成機能の実装。

進め方: まず起動確認後、1) の正規化強化から着手してください。完了後に 2) の検証と修正を行い、差分をコミットしてください。
```

## 追加作業記録（2025-11-03）
- 出品CSV生成強化
  - Shift-JIS向け正規化を適用、列マッピングを整備
  - `takane` 自動計算（priceのX%上・UIで％指定）
  - タイトル出力の有無を選択可（UIトグル）
- 除外ロジック/可視化
  - コメントに「除外」または発送方法がFBA以外を出品CSVから除外
  - テーブルで「除外商品確認」トグル: 非除外行を淡い青＋太字で強調、再クリックで解除
- 保存・出力まわり
  - 出品CSVの保存先（暫定）を `D:\せどり総合\店舗せどり仕入リスト入れ\仕入帳\20251102つくばルート` に固定
  - 同名ファイルは `(1)(2)…` を自動付与（共通ユーティリティ `resolve_unique_path`）
  - プレビュー出力名を `inventory_preview.csv` に変更し誤用防止
- 設定の永続化
  - 出品リスト生成設定（タイトル出力ON/OFF、高値設定ON/OFF、％）を QSettings で保存/読込
- 保存履歴・編集反映
  - 保存履歴の日時を日本時間表示に変更（`datetime(...,'localtime')`）
  - 保存前にテーブル内容を同期し、手入力の「除外」や「発送方法」編集が保存/読込で維持されるよう修正

### 古物台帳（新規実装・最小導線）
- DB: `python/desktop/database/ledger_db.py` 追加
  - `purchase_rows`/`classification_cache`/`ledger_entries` を作成
  - `insert_ledger_rows`/`query_ledger` を提供
- UI: `python/desktop/ui/antique_widget.py` を2タブ構成に拡張
  - サブタブ1「入力・生成」
    - 相手区分（店舗/フリマ/個人）を1行表示に圧縮
    - 区分別テンプレートを動的表示（必要項目のみ）
    - 共通項目: 取引日/13区分/品目/品名/数量/単価/識別情報
    - 区分別必須チェックを実装（未入力はコミット不可）
    - コミットで `ledger_entries` に保存
  - サブタブ2「閲覧・出力」
    - 統一スキーマで全列保持＋列グループ表示（共通/店舗/フリマ/個人）
    - 相手区分フィルタ変更で該当グループ自動ON
    - 期間フィルタ→DBから再読込、フィルタ結果をShift-JIS CSVで出力
    - 列幅はセッション保存（QSettings）

次チャット開始時は「古物台帳の区分別テンプレの調整」や「閲覧・出力のフィルタ拡張（店舗名/ID等）」の続きから着手できます。

## 追加作業記録（2025-02-XX 最新）
### 古物台帳機能改善
- 品目選択の改善
  - 品目名から番号（①②等）を削除して表示
  - デフォルト選択を「道具類」に設定
  - 既存データとの互換性対応（番号付き品目名の正規化処理）
- 取引日の時刻削除
  - 取引日から時刻部分を削除して yyyy-MM-dd 形式に統一
  - 仕入管理からの取込時、テーブル表示時、CSV出力時に適用
- 取込プレビューテーブルの改善
  - 品目列を常にプルダウン化（マッチした品目も変更可能）
  - 値がない場合やマッチしない場合はデフォルトで「道具類」を選択
- 実装詳細
  - `_normalize_category_name()`: 品目名の番号削除と正規化
  - `_normalize_date()`: 日付文字列から時刻部分を削除
  - 取込プレビューテーブル（`_refresh_store_list_table()`）で品目列を常にプルダウン化



## 追加作業記録（2025-11-06）
- 古物台帳（閲覧・出力）と仕入管理の改善（検証対応まとめ）
  - 表示のみ50文字省略。保存・CSV/Excelは全文を使用（UserRoleに原文保持）。
  - 取込プレビュー一括登録の必須チェックを行単位に変更。品目は初期選択も内部に反映。
  - 店舗情報を正規カラムに保存（支店=`counterparty_branch`、店舗住所=`counterparty_address`、連絡先=`contact`）。
  - 取引方法（`transaction_method`）を保存。店舗は「買受」。
  - 「None」表示を廃止し、未入力は空欄表示。
  - Excel出力をCSVと同一仕様に統一（日本語ヘッダ・列順保持・None→空）。
  - 古物台帳生成完了後はDBから再読込して一覧が消えないように修正。
  - デバッグ機能: 「全データ削除」ボタンを閲覧・出力タブに追加。

### 引き継ぎポイント
- 仕入管理 `inventory_widget.py`
  - 表示: 50文字省略だが、セルのUserRole/ToolTipに全文保持。
  - 保存: `sync_inventory_data_from_table()` → `get_table_data()`がUserRoleから全文を取り出す。
  - 既存の切詰め保存データは原文復元不可。元CSVから再取込→保存で置換を推奨。
- 古物台帳 `antique_widget.py`
  - 一括登録は行ごと必須チェック（品名/識別情報/仕入先名/品目）。
  - 登録後・単票保存後ともに `reload_ledger_rows()` を呼び出し即時反映。
  - Excel出力は `self.column_headers/self.column_keys` で日本語ヘッダ・順序固定。
  - UI列名を「店舗住所」「個人住所」に変更済み。
- DB `ledger_db.py`
  - 互換マイグレーション付きで新規カラムを追加：`counterparty_branch`/`counterparty_address`/`contact`/`transaction_method`。
  - デバッグ用 `delete_all()` を実装。

### 今後の確認/課題
- 仕入管理→保存→読み込みのフルテキスト維持を実データで最終確認（デバッグログあり）。
- 住所/支店/連絡先のマッピング漏れケースがあれば例を収集して調整。
- 既存の保存データで50字切りされているものは元ファイルからの再登録で対応。

### 追加実装（2025-11-06 完了）
- **品目編集の自動学習機能**
  - プルダウン変更時に商品名・識別情報から自動学習
  - `ledger_category_dict`テーブル: キーワード→品目のマッピング（重み付き）
  - `ledger_id_map`テーブル: JAN/ASIN→品目の直接マッピング（高信頼度）
  - 次回取込時は学習データを優先して品目を自動推定
- **ユーザー辞書UI変更**
  - 13品目を縦に展開、各品目の右にカンマ区切りキーワード入力欄
  - 既存の{キーワード: 品目}形式から自動変換
- **PWA側の表示改善**
  - `InventoryDataGrid.tsx`: 商品名は表示のみ50文字省略（CSS ellipsis）
  - ツールチップ（title属性）で全文表示
  - データは全文保持（保存・API送信は切らない）

### Gitコミット（2025-11-06）
- コミット: `53fb83b` - 古物台帳・仕入管理: 品目学習機能、表示改善、データ保存改善
- 変更ファイル:
  - `python/desktop/database/ledger_db.py` - 学習用テーブル追加、マイグレーション
  - `python/desktop/ui/antique_widget.py` - 学習機能、UI改善、Excel出力修正
  - `python/desktop/ui/inventory_widget.py` - 全文保存対応
  - `pwa/src/app/components/InventoryDataGrid.tsx` - 表示のみ省略対応
  - `docs/handover_prompt_route_summary_complete.md` - 引き継ぎドキュメント更新

### OCR/保証書マッチング（2025-11-06 着手）
- プロジェクト方針確定（レシート=日付/店舗/金額、保証書=商品名）
- 新規DB実装: `products` テーブルを追加（SKU主キー）
  - ファイル: `python/desktop/database/product_db.py`
  - 項目: `sku/jan/asin/product_name/purchase_date/purchase_price/quantity/store_code/store_name/receipt_id/warranty_*`
- 目的:
  - 返品照合（SKUベース）
  - 保証情報（期間・満了日・保証書画像パス等）の保存先整備
  - レシート/保証書OCR後の自動紐付け先として利用
- 新規DB実装: レシート/学習/保証書テーブルを追加
  - `python/desktop/database/receipt_db.py`: `receipts`, `receipt_match_learnings`
    - 項目（抜粋）: `file_path/purchase_date/store_name_raw/store_code/subtotal/tax/discount_amount/total_amount/paid_amount/ocr_text`
  - `python/desktop/database/warranty_db.py`: `warranties`
    - 項目（抜粋）: `file_path/ocr_product_name/sku/matched_confidence`
  - 方針: 
    - レシートは同日・店舗部分一致・金額一致（誤差±10円）で候補提示
    - クーポン/値引きは確定申告用台帳にのみ出力（古物台帳は除外）
- OCRサービス実装
  - `python/desktop/services/ocr_service.py`: Tesseract優先、GCVフォールバック
  - `python/desktop/utils/image_processor.py`: 画像前処理（グレースケール、コントラスト調整）
  - 依存関係追加: `Pillow`, `pytesseract`（`requirements.txt`）
  - 日本語対応: Tesseractに`jpn+eng`言語指定
  - レシートサービス実装: `python/desktop/services/receipt_service.py`
    - 画像保存→OCR→日付/店舗名（生）/小計・税・値引・合計・支払を抽出
    - `ReceiptDatabase` に保存（`receipts`）
  - マッチングサービス実装: `python/desktop/services/receipt_matching_service.py`
    - 条件: 同日、店舗部分一致（店舗マスタ/学習）、金額一致（`(合計-値引)` とアイテム合計の差 ≤ ±10円）
    - 学習: 手動修正を `receipt_match_learnings` に蓄積、レシート`store_code`も更新


---
次チャットでは、上記「引き継ぎポイント」を前提に動作確認の続き、または残タスクの実装（フィルタ拡張や印刷レイアウト調整など）から着手してください。
## 追加作業記録（2025-11-05）
- 古物台帳（入力・生成）
  - 相手区分パネルの高さ拡張、取込/折畳みボタンを追加（テンプレは初期状態で畳む）。
  - 取込元をCSV→仕入管理の「取り込んだデータ一覧」に変更。未展開時はガイド表示。
  - プレビュー列を「共通＋店舗」構成に統一。数量×単価で金額自動算出。
  - 13品目（区分）を正式対応（①美術品類〜⑬金券類）。ユーザー辞書による品目自動割当、未マッチはプルダウン手選択可。
  - ユーザー辞書編集タブを追加（キーワード⇄品目の編集/保存）。
  - 取込時の店舗マスタ連携を強化：支店（店舗名）/住所/電話を補完。
  - 法人マスタ連携を追加：支店名→チェーン名をキーワードマッチし、仕入先名（法人名）を自動入力。
  - 取引方法列を追加（買受固定）。


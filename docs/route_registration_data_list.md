# ルート登録機能 保存データ一覧

ルート登録機能で保存されるデータベース情報の一覧です。

## データベース構成

### 1. **route_summaries** テーブル（ルート基本情報）

ルートの基本情報と統計データを保存します。

| カラム名 | データ型 | 必須 | 説明 | 取得元 |
|---------|---------|------|------|--------|
| `id` | INTEGER | 自動 | 主キー（自動採番） | - |
| `route_date` | DATE | ✓ | ルート日付 | カレンダー入力 |
| `route_code` | TEXT | ✓ | ルートコード（例：C1, H1） | プルダウン選択 |
| `departure_time` | DATETIME | - | 出発日時 | ルート日付 + 出発時間（HH:MM） |
| `return_time` | DATETIME | - | 帰宅日時 | ルート日付 + 帰宅時間（HH:MM） |
| `toll_fee_outbound` | REAL | - | 往路高速代（円） | SpinBox入力 |
| `toll_fee_return` | REAL | - | 復路高速代（円） | SpinBox入力 |
| `parking_fee` | REAL | - | 駐車代（円） | 固定値0（未実装） |
| `meal_cost` | REAL | - | 食事代（円） | 固定値0（未実装） |
| `other_expenses` | REAL | - | その他経費（円） | 固定値0（未実装） |
| `remarks` | TEXT | - | 備考 | TextEdit入力 |
| `total_working_hours` | REAL | - | 総稼働時間（時間） | 計算サービス自動計算 |
| `estimated_hourly_rate` | REAL | - | 想定時給（円/時間） | 計算サービス自動計算 |
| `total_gross_profit` | REAL | - | 総想定粗利（円） | 照合処理・再計算で自動更新 |
| `total_item_count` | INTEGER | - | 総仕入点数（個） | 店舗訪問詳細の合計 |
| `purchase_success_rate` | REAL | - | 仕入成功率（%） | 計算サービス自動計算 |
| `avg_purchase_price` | REAL | - | 平均仕入価格（円） | 計算サービス自動計算 |
| `created_at` | DATETIME | 自動 | 作成日時 | CURRENT_TIMESTAMP |
| `updated_at` | DATETIME | 自動 | 更新日時 | CURRENT_TIMESTAMP |

---

### 2. **store_visit_details** テーブル（店舗訪問詳細情報）

各ルートに紐づく店舗訪問の詳細情報を保存します（1ルート = 複数店舗）。

| カラム名 | データ型 | 必須 | 説明 | 取得元 |
|---------|---------|------|------|--------|
| `id` | INTEGER | 自動 | 主キー（自動採番） | - |
| `route_summary_id` | INTEGER | ✓ | ルートサマリーID（外部キー） | route_summaries.id |
| `store_code` | TEXT | ✓ | 仕入れ先コード（例：C1-001） | 店舗マスタ |
| `visit_order` | INTEGER | - | 訪問順序（1, 2, 3...） | 自動設定・ドラッグ&ドロップ |
| `store_in_time` | DATETIME | - | 店舗IN日時 | ルート日付 + IN時間（HH:MM） |
| `store_out_time` | DATETIME | - | 店舗OUT日時 | ルート日付 + OUT時間（HH:MM） |
| `stay_duration` | REAL | - | 滞在時間（分） | 自動計算（OUT - IN） |
| `travel_time_from_prev` | REAL | - | 前店舗からの移動時間（分） | 自動計算 |
| `distance_from_prev` | REAL | - | 前店舗からの距離（km） | 未実装（固定NULL） |
| `store_gross_profit` | REAL | - | 想定粗利（円） | 照合処理・再計算で自動更新 |
| `store_item_count` | INTEGER | - | 仕入れ点数（個） | 照合処理・再計算で自動更新 |
| `purchase_success` | INTEGER | - | 仕入成功フラグ（0/1） | 固定0（未実装） |
| `no_purchase_reason` | TEXT | - | 仕入なし理由 | 固定NULL（未実装） |
| `store_rating` | INTEGER | - | 店舗評価（★1-5） | 星評価ウィジェット |
| `store_notes` | TEXT | - | メモ | テーブル入力 |
| `next_visit_recommendation` | TEXT | - | 次回訪問推奨日 | 固定NULL（未実装） |
| `category_breakdown` | TEXT | - | カテゴリ別内訳 | 固定NULL（未実装） |
| `competitor_present` | INTEGER | - | 競合在庫フラグ（0/1） | 固定0（未実装） |
| `inventory_level` | TEXT | - | 在庫状況 | 固定NULL（未実装） |
| `trouble_occurred` | INTEGER | - | トラブル発生フラグ（0/1） | 固定0（未実装） |
| `trouble_details` | TEXT | - | トラブル詳細 | 固定NULL（未実装） |
| `created_at` | DATETIME | 自動 | 作成日時 | CURRENT_TIMESTAMP |
| `updated_at` | DATETIME | 自動 | 更新日時 | CURRENT_TIMESTAMP |

---

## データ取得・表示の流れ

### 保存時の処理

1. **ユーザー入力**
   - ルート日付・ルートコード・出発/帰宅時間・経費・備考
   - 店舗訪問順序・IN/OUT時間・評価・メモ

2. **自動計算**
   - 滞在時間（OUT - IN）
   - 移動時間（前店舗OUT → 現在店舗IN）

3. **照合処理実行時**
   - 仕入管理データから店舗コードでマッチング
   - 想定粗利・仕入れ点数を自動更新
   - ルートサマリーの総合計も自動更新

4. **DB保存**
   - `route_summaries` に1レコード
   - `store_visit_details` に店舗数分のレコード
   - 外部キー制約で整合性を保証

### 読み込み時の処理

1. ルートサマリー情報を取得
2. 店舗訪問詳細を取得（訪問順序でソート）
3. 店舗マスタから店舗名を補完（`store_code` → `store_name`）

---

## 実際の保存例

### route_summaries の例

```json
{
  "id": 1,
  "route_date": "2025-11-02",
  "route_code": "C1",
  "departure_time": "2025-11-02 08:30:00",
  "return_time": "2025-11-02 18:00:00",
  "toll_fee_outbound": 1500,
  "toll_fee_return": 1500,
  "parking_fee": 0,
  "meal_cost": 0,
  "other_expenses": 0,
  "remarks": "通常ルート",
  "total_working_hours": 9.5,
  "estimated_hourly_rate": 3500,
  "total_gross_profit": 45000,
  "total_item_count": 16,
  "purchase_success_rate": 85.5,
  "avg_purchase_price": 2500,
  "created_at": "2025-11-02 10:00:00",
  "updated_at": "2025-11-02 15:30:00"
}
```

### store_visit_details の例（3店舗分）

```json
[
  {
    "id": 1,
    "route_summary_id": 1,
    "store_code": "C1-001",
    "visit_order": 1,
    "store_in_time": "2025-11-02 09:00:00",
    "store_out_time": "2025-11-02 10:30:00",
    "stay_duration": 90,
    "travel_time_from_prev": 30,
    "store_gross_profit": 15000,
    "store_item_count": 5,
    "store_rating": 4,
    "store_notes": "在庫豊富"
  },
  {
    "id": 2,
    "route_summary_id": 1,
    "store_code": "C1-002",
    "visit_order": 2,
    "store_in_time": "2025-11-02 11:00:00",
    "store_out_time": "2025-11-02 12:00:00",
    "stay_duration": 60,
    "travel_time_from_prev": 30,
    "store_gross_profit": 20000,
    "store_item_count": 8,
    "store_rating": 5,
    "store_notes": ""
  },
  {
    "id": 3,
    "route_summary_id": 1,
    "store_code": "C1-003",
    "visit_order": 3,
    "store_in_time": "2025-11-02 13:00:00",
    "store_out_time": "2025-11-02 15:00:00",
    "stay_duration": 120,
    "travel_time_from_prev": 60,
    "store_gross_profit": 10000,
    "store_item_count": 3,
    "store_rating": 3,
    "store_notes": "混雑"
  }
]
```

---

## データ特性

### 必須項目

- **route_summaries**: `route_date`, `route_code`
- **store_visit_details**: `route_summary_id`, `store_code`

### 自動計算項目

- `stay_duration` = `store_out_time` - `store_in_time`
- `travel_time_from_prev` = 前店舗OUT時刻 - 現在店舗IN時刻
- `store_gross_profit` = 店舗別の仕入商品の見込み利益合計
- `store_item_count` = 店舗別の仕入れ個数の合計
- `total_gross_profit` = 全店舗の`store_gross_profit`の合計
- `total_item_count` = 全店舗の`store_item_count`の合計

### 外部キー制約

- `store_visit_details.route_summary_id` → `route_summaries.id`
- `ON DELETE CASCADE`: ルートサマリー削除時に店舗訪問詳細も自動削除

### タイムスタンプ自動更新

- `created_at`: レコード作成時に自動設定
- `updated_at`: レコード更新時に自動更新（トリガー）

---

## 関連機能

- **保存**: `RouteDatabase.add_route_summary()` / `add_store_visit()`
- **読み込み**: `RouteDatabase.get_route_summary()` / `get_store_visits_by_route()`
- **更新**: `RouteDatabase.update_route_summary()` / `delete_store_visit()` + `add_store_visit()`
- **削除**: `RouteDatabase.delete_route_summary()` （CASCADEで関連データも削除）

---

**更新日**: 2025-11-02  
**データベース**: `python/desktop/data/hirio.db` (SQLite3)


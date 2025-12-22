# 店舗コード（store_code）移行計画

## 概要
`supplier_code`（仕入れ先コード）から`store_code`（店舗コード）への移行計画です。
将来的に公開アプリにする際は、`store_code`で統一する設計にします。

## 実装完了項目

### ✅ ステップ1: DBにstore_codeカラムを追加
- `stores`テーブルに`store_code TEXT UNIQUE`カラムを追加
- マイグレーション処理を実装（既存DBにも自動追加）

### ✅ ステップ2: 店舗一覧テーブルに店舗コード列を追加
- 店舗マスタの店舗一覧テーブルに「店舗コード」列を追加
- 列順: `ID / 所属ルート名 / ルートコード / 店舗コード / 仕入れ先コード / 店舗名 / 住所 / 電話番号 / 備考`

### ✅ ステップ3: 店舗コード自動付与機能
- 「店舗コード再付番」ボタンを追加
- チェーン店コードマッピングを参照して連番で生成（例: `BO-01`, `BO-02`）
- その他用のデフォルトコードにも対応

## 調査結果: supplier_code使用箇所

### 1. データベース層（`python/desktop/database/store_db.py`）
- `supplier_code TEXT UNIQUE` - テーブル定義
- `add_store()` - 追加時に保存
- `update_store()` - 更新時に保存
- `get_store_by_supplier_code()` - 仕入れ先コードで検索
- `check_supplier_code_exists()` - 重複チェック
- `get_max_supplier_code_for_route()` - ルート別最大コード取得
- `get_next_supplier_code_for_route()` - ルート別次コード生成
- `get_next_supplier_code_from_store_name()` - 店舗名から生成

**対応方針:**
- 既存メソッドは残す（後方互換性のため）
- 新規メソッドは`store_code`ベースで実装済み
- 段階的に`store_code`ベースのメソッドに移行

### 2. UI層（`python/desktop/ui/store_master_widget.py`）
- 店舗編集ダイアログで「仕入れ先コード」入力欄
- 店舗一覧テーブルで「仕入れ先コード」列表示
- 検索機能で「仕入れ先コード」検索

**対応方針:**
- 店舗コード列は追加済み
- 仕入れ先コード列は当面残す（非表示化は後で検討）
- 検索機能は両方に対応

### 3. その他の使用箇所（要確認）
以下のファイルでも`supplier_code`が使用されている可能性があります：

- `python/desktop/ui/receipt_widget.py` - レシート管理
- `python/desktop/ui/route_summary_widget.py` - ルートサマリー
- `python/desktop/ui/inventory_widget.py` - 仕入管理
- `python/desktop/ui/antique_widget.py` - 古物台帳
- `python/desktop/services/receipt_matching_service.py` - レシート照合
- `python/desktop/utils/template_generator.py` - テンプレート生成
- `python/desktop/utils/excel_importer.py` - Excelインポート

**対応方針:**
- 各ファイルを個別に確認
- 店舗を識別するキーとして使用している箇所を`store_code`に置き換え
- CSV/Excel出力も`store_code`ベースに変更

## 移行スケジュール

### Phase 1: 基盤整備（完了）
- ✅ DBに`store_code`カラム追加
- ✅ UIに店舗コード列追加
- ✅ 自動付与機能実装

### Phase 2: 機能移行（今後実施）
- [ ] 各機能で`store_code`をメインキーとして使用
- [ ] CSV/Excel出力で`store_code`を使用
- [ ] 検索・照合処理を`store_code`ベースに変更
- [ ] 既存データの`store_code`付与完了確認

### Phase 3: 公開前（将来）
- [ ] すべての機能が`store_code`で正常動作することを確認
- [ ] `supplier_code`を非表示化 or 削除
- [ ] ドキュメント更新

## 注意事項

1. **後方互換性の維持**
   - 移行期間中は`supplier_code`も維持
   - 既存データとの整合性を保つ

2. **データ整合性**
   - `store_code`と`supplier_code`の対応関係を維持
   - バックアップを取得してから作業

3. **段階的移行**
   - 一度にすべてを変更せず、機能ごとに移行
   - 各機能の動作確認を徹底

## 関連ファイル

- `python/desktop/database/store_db.py` - データベース操作
- `python/desktop/ui/store_master_widget.py` - 店舗マスタUI
- `python/desktop/ui/settings_widget.py` - チェーン店コードマッピング設定


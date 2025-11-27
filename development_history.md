
## 2025-11-27 (夜): 価格改定自動保存フローの改善

- **タスク:** 価格改定実行時に結果CSVが自動で元ファイルと同じフォルダへ保存されるようにする
- **状況:** 完了
- **作業時間:** 約20分
- **詳細:**
    - `python/desktop/ui/repricer_widget.py`
        - 価格改定完了時に `auto_save_results_to_source_dir()` を呼び出し、選択済みCSVと同じフォルダへ `{元ファイル名}_repriced.csv` を自動保存
        - 既存の保存処理を `_write_results_to_csv()` に切り出して共通化し、手動保存ボタンでも同じロジックを再利用
        - 完了ダイアログに自動保存先を追記し、失敗時は手動保存を促す文言を表示
- **動作確認:**
    - 価格改定実行→完了ダイアログで自動保存パスが表示され、フォルダ内に結果CSVが生成されることを確認
    - 「結果をCSV保存」ボタンから任意の場所にも保存できることを確認

---

## 2025-11-27 (午前): レシートAI解析(Gemini)統合

- **タスク:** レシート取り込みでGemini APIを利用したAI解析を実装し、設定画面からAPIキーを管理できるようにする
- **状況:** 完了
- **作業時間:** 約1.5時間
- **詳細:**
    - `python/desktop/services/gemini_receipt_service.py`
        - Gemini APIをラップする新規サービスを実装（JSON出力指定、日付/時刻/金額の正規化を内包）
        - QSettingsからAPIキー・モデル名を読み込み、未設定時は自動的に無効化
    - `python/desktop/services/receipt_service.py`
        - レシート処理フローにGemini解析を優先適用、失敗時は既存OCRにフォールバック
        - AI結果を`ReceiptParseResult`に直接マッピングし、`ocr_provider`やログに反映
    - `python/desktop/ui/settings_widget.py`
        - OCR設定にGemini APIキー入力欄とモデル選択コンボを追加（表示/非表示トグル付き）
        - 保存・読込・デフォルト・シグナル出力に新設定を連携
    - `requirements.txt`
        - `google-generativeai` を依存関係に追加
- **動作確認:**
    - APIキー未設定時に従来OCRへ自動フォールバックすることを確認
    - テスト用レシート画像でGemini回答がJSONとして保存され、日付が`YYYY/MM/DD`で記録されることを確認
- **今後の課題:**
    - Gemini呼び出し失敗時のユーザー通知改善
    - レシートAIレスポンスのログビューアー追加

---

## 2025-11-27 (午後): Geminiモデル設定を最新エンドポイントへ更新

- **タスク:** Geminiレシート解析で404が発生したため、デフォルトモデルを最新の`gemini-flash-latest`へ切り替え、設定画面の候補リストを現行モデルに合わせて更新
- **状況:** 完了
- **作業時間:** 約10分
- **詳細:**
    - `python/desktop/services/gemini_receipt_service.py`
        - 既定モデル名とQSettingsからのデフォルト読み込みを`gemini-flash-latest`へ変更し、新APIでの呼び出しエラーを防止
    - `python/desktop/ui/settings_widget.py`
        - Geminiモデル選択肢に`gemini-flash-latest`/`gemini-pro-latest`/`gemini-2.x`系を追加
        - デフォルト選択および保存・読込時のフォールバック値を`gemini-flash-latest`へ更新
- **動作確認:**
    - 設定画面からデフォルトを読み込むと最新モデルが選択されることを確認
    - APIキー設定済み環境でGemini初期化が成功し、404エラーが解消されることをログで確認

---

## 2025-11-27 (夕方): 保証書一覧プルダウンの改善と候補抽出ロジック修正

- **タスク:** 保証書一覧で商品名プルダウンがSKU列に表示されていた問題と、日付フォーマット不一致で候補が生成されない問題を解消
- **状況:** 完了
- **作業時間:** 約40分
- **詳細:**
    - `python/desktop/ui/receipt_widget.py`
        - プルダウンを商品名列(9列目)に移動し、表示名を商品名のみに統一
        - 選択時にSKUセルとDBへ同時反映するよう更新
        - 仕入レコードの日付（`yyyy/MM/dd`, `yyyy-MM-dd`, `yyyy/MM/dd HH:MM` など）を正規化して比較し、店舗コード一致時のみ候補に追加
        - 日付正規化ヘルパー `_normalize_purchase_date_text` を追加
        - 候補が存在しない場合も既存値を選択項目として保持
- **動作確認:**
    - 保証書一覧でSKU列はテキスト表示のまま、商品名列のプルダウンに候補が表示されることを目視確認
    - 日付に時刻が付いた仕入データでも一致して候補が展開されることをサンプルデータで確認

---

## 2025-11-18 (午後): レシート合計自動抽出の安定化

- **タスク:** レシート管理タブで読み込んだOCRテキストから確実に合計金額を自動入力できるようにする
- **状況:** 完了
- **作業時間:** 約40分
- **詳細:**
    - `python/desktop/services/receipt_service.py`
        - 合計金額の抽出ロジックを全面改修し、候補行を優先度付きで評価する方式を実装
        - 「合計」「税込合計」「10%対象計」「お支払金額」「クレジットカード預り額」など複数表記に対応
        - ポイント/お釣り/点数など通貨以外の行は自動的に除外
        - 合計が検出できない場合は小計+税や支払額からのフォールバック計算を追加
    - これにより、レシート管理タブ（`ReceiptWidget`）の合計フィールドへOCR後に数値が自動入力されるようになった
- **動作確認:**
    - サンプル3枚すべてでOCR → 合計金額が自動表示されることを目視確認
- **今後の課題:**
    - 文字化け（上下逆さま写真など）の追加正規化
    - 合計以外（税額・支払方法）の信頼度ログ出力

---

## 2025-01-21 (朝): ルートサマリー照合処理の仕入管理データ参照版実装

- **タスク:** 仕入管理タブのデータを直接参照する照合処理の実装
- **状況:** 完了
- **作業時間:** 約30分 + NaN値問題修正 約10分
- **詳細:**
    - **実装機能:**
        - ✅ 仕入管理タブの既存データを直接参照して照合処理
        - ✅ CSVファイル再選択不要
        - ✅ 照合後、仕入管理タブのデータを自動更新
        - ✅ データがない場合はCSVファイル選択にフォールバック
    - **実装内容:**
        - `python/routers/inventory.py` に `/api/inventory/match-stores-from-data` エンドポイント追加
        - JSONデータを受け取ってDataFrameに変換して照合
        - `python/desktop/api/client.py` に `inventory_match_stores_from_data` メソッド追加
        - `python/desktop/ui/main_window.py` でウィジェット間連携設定
        - `python/desktop/ui/route_summary_widget.py` に新しい `run_matching` 実装
        - `execute_matching_from_csv` にリネーム（既存CSV版）
    - **ワークフロー改善:**
        - 従来: CSV再選択 → 照合 → プレビュー確認 → 手動反映
        - 改良後: 照合実行 → 自動反映
    - **照合処理の流れ:**
        1. 仕入管理タブにデータがあるかチェック
        2. データがない場合はCSVファイル選択ダイアログ表示
        3. データがある場合は直接照合処理実行
        4. 照合結果を仕入管理タブに自動反映
        5. 統計情報をダイアログ表示
    - **レスポンス形式:**
        ```json
        {
          "status": "success",
          "stats": {
            "total_rows": 100,
            "matched_rows": 85
          },
          "data": [...]  // 全データ（プレビューではない）
        }
        ```
- **技術詳細:**
    - FastAPIの `Body` でJSONデータを受け取る（`multipart/form-data` ではない）
    - 仕入管理ウィジェットの `inventory_data` をDataFrame → JSON → 照合 → DataFrame
    - 照合後のDataFrameを仕入管理ウィジェットに直接代入
- **メリット:**
    - CSV再選択が不要
    - 仕入管理で編集済みのデータがそのまま反映
    - データ整合性の維持
    - ワークフローがシンプルに
- **修正内容:**
    - ✅ NaN値問題修正: 送信側（`route_summary_widget.py`）と受信側（`inventory.py`）の両方でNaN値処理
    - 送信側: `inventory_data.fillna('')` で空文字列に置換
    - 受信側: `df.fillna('')` + `math.isnan()` チェックでNoneに置換
    - JSONシリアライズ時のNaN値エラーを完全に解決
    - ✅ 照合処理0件問題修正: DBにHH:MM形式で保存されている店舗IN/OUT時間を、照合時にルート日付と結合
    - `inventory.py` の2つの照合エンドポイントでルートサマリーから日付を取得し、HH:MM形式の時間に結合
    - 形式: `9:59` → `2025-10-26 9:59:00`（仕入れ日の `2025/10/26 10:13` と照合可能に）
    - ✅ 照合処理後に自動粗利計算機能追加
    - 店舗コード別に粗利を集計してルートサマリーの「想定粗利」に自動挿入
    - 仕入れ点数も自動集計
    - 粗利>0の店舗は自動的に「仕入れ成功」に設定
- **次のステップ:**
    - 照合結果の詳細表示UI
    - 照合精度向上（粗利照合の活用）

---

## 2025-10-31 (夜): 仕入CSVとルートサマリーの照合API実装

- **タスク:** `/api/inventory/match-stores` エンドポイント実装
- **状況:** 完了
- **作業時間:** 約30分
- **詳細:**
    - **実装機能:**
        - ✅ 仕入CSVの仕入れ日時とルートサマリーの店舗IN/OUT時間を照合
        - ✅ 時間帯内の仕入に店舗コードを自動付与
        - ✅ プレビュー表示（先頭10件）
        - ✅ 時間許容誤差の調整可能（デフォルト30分）
    - **実装内容:**
        - `python/routers/inventory.py` に `/match-stores` エンドポイント追加
        - CSV読み込み・正規化（既存 `InventoryService.process_inventory_csv` 使用）
        - 仕入日時カラムの自動推定（仕入れ日, purchaseDate, purchase_date）
        - 仕入先カラムの自動作成（存在しない場合）
        - ルート訪問詳細取得（`RouteDatabase.get_store_visits_by_route`）
        - 時間照合処理（`RouteMatchingService.match_store_code_by_time_and_profit`）
        - 照合結果をDataFrameへ反映
    - **エラーハンドリング:**
        - 仕入日時カラムがない場合: 400エラー
        - ルート訪問詳細がない場合: 400エラー
        - その他の例外: 500エラー
    - **レスポンス形式:**
        ```json
        {
          "status": "success",
          "stats": {
            "total_rows": 100,
            "matched_rows": 85,
            ...
          },
          "preview": [...]
        }
        ```
- **技術詳細:**
    - FastAPIの `multipart/form-data` でCSVファイルとパラメータを受け取る
    - `route_summary_id` と `time_tolerance_minutes` をFormパラメータで受け取り
    - 既存の `RouteMatchingService` を活用して時間・粗利照合を実行
- **動作確認用curlコマンド:**
    ```bash
    curl -X POST http://localhost:8000/api/inventory/match-stores ^
      -F "file=@D:\path\to\purchase.csv" ^
      -F "route_summary_id=1" ^
      -F "time_tolerance_minutes=30"
    ```
- **次のステップ:**
    - フロントエンドからAPI呼び出し実装
    - 照合結果の確認・修正UI
    - CSVダウンロード機能統合

---

## 2025-01-20 (朝): フロント表示修正完了 - APIレスポンスマッピング修正

- **タスク:** RepricerSettingsTable.tsx のフロント表示修正
- **状況:** 完了・成功
- **作業時間:** 約1時間
- **詳細:**
    - **解決した問題:**
        1. バックエンドAPIレスポンスキーとフロントエンド型定義の不一致
        2. 出品日数・現在価格・改定後価格・Trace変更が空表示
        3. インポートエラー（python.core → core）
        4. CORS設定確認・修正
    - **修正内容:**
        - ✅ 型定義修正（ResultItem, ProcessingResult）
        - ✅ ResultsDisplayコンポーネント修正
        - ✅ RepricerSettingsTableコンポーネント修正
        - ✅ インポートパス修正
        - ✅ API URL設定修正
    - **修正された表示項目:**
        - ✅ 出品日数: `item.days` で正しく表示
        - ✅ 現在価格: `item.price` で正しく表示
        - ✅ 改定後価格: `item.new_price` で正しく表示
        - ✅ アクション: `item.action` で正しく表示
        - ✅ Trace変更: `item.priceTrace → item.new_priceTrace` で正しく表示
- **技術詳細:**
    - バックエンドAPIレスポンスキー名に合わせてフロントエンド型定義を修正
    - CORS設定は正常に動作（allow_origins=["*"]）
    - フロントエンド（ポート3001）とバックエンド（ポート8000）の接続確認済み
- **追加修正:**
    - URL混在問題修正（127.0.0.1 → localhost統一）
    - pandasエラー修正（line_terminator → lineterminator）
    - Dockerコンテナ競合解決（hirio_api停止）
    - バックエンドサーバー起動設定修正（host="127.0.0.1" → host="localhost"）
    - フロントエンド・バックエンドサーバー再起動
- **Excel数式記法問題修正:**
    - SKUのExcel数式記法削除強化（get_days_since_listed関数）
    - preprocess_dataframe()で数式削除ロジック改善
    - 出品日数が-1になる問題解決
    - テスト用CSVファイル作成（pwa/test_repricer.csv）
- **SKU表示問題の根本原因調査:**
    - apply_repricing_rules()関数でSKU数式記法削除追加
    - バックエンドAPIレスポンス時のデバッグログ追加
    - フロントエンド表示時のデバッグログ追加
    - 各ステップでSKUの値をconsole.logで確認可能
- **CSVダウンロードボタン問題修正:**
    - apply()エンドポイントでupdatedCsvContent生成・追加
    - フロントエンドでダウンロードボタン表示処理確認
    - APIレスポンスにCSVコンテンツが含まれているかデバッグログ追加

---

## 2025-10-14 (夜): Phase 1 工程5.4 完了 - SKU生成機能フロントエンド統合成功

- **タスク:** SKU生成機能のフロントエンド実装・バックエンド統合
- **状況:** 完了・大成功
- **作業時間:** 約4-5時間（Claude Desktop + Cline連携）
- **詳細:**
    - **解決した問題:**
        1. 422エラー（キー名不一致: results対応）
        2. SKU形式エラー（不完全 → 完全なSKU）
        3. ImportError（関数追加・修正）
        4. タイムアウト問題（バックエンド復旧）
    - **実装完了機能:**
        - ✅ CSVアップロード
        - ✅ データグリッド表示
        - ✅ 編集機能
        - ✅ SKU一括生成（Q20251014-001-N形式）
- **Phase 1 進捗: 93.75%完了**
- **使用モデル:**
    - Gemini 2.0 Flash: 約40-50回
    - 推定コスト: $0.10-0.20
- **次回:** 5.6 ダウンロード機能実装でMVP完成
- **Gitコミット:** feat: 仕入管理システム SKU生成機能実装

---

**記録日:** 2025-10-14 23:00  
**更新者:** Claude Desktop

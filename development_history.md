## 2025-02-XX: 証憑管理機能の改善

- **タスク:** 証憑管理（レシート管理・保証書管理）の機能改善
- **状況:** 完了
- **作業時間:** 約2時間
- **詳細:**
    - **レシート管理の確定ボタン修正**
        - `python/desktop/ui/receipt_widget.py`:
            - `confirm_receipt_linkage`メソッドにデバッグログを追加
            - `product_widget`が設定されていない場合の警告メッセージを追加
            - 処理対象がなかった場合の適切なメッセージを追加
    - **保証書一覧の保証期間・保証最終日連動機能修正**
        - `python/desktop/ui/receipt_widget.py`:
            - 列インデックスの修正（保証期間(日): 列9, 日付: 列3, 保証最終日: 列10）
            - 保証期間(日)を入力すると日付+保証期間で保証最終日を自動計算
            - 保証最終日を設定すると日付から逆算して保証期間(日)を自動計算
            - 保証最終日のデフォルト値を日付（保証書の日付）に設定（保証期間がない場合）
    - **保証書一覧に商品追加機能を実装**
        - `python/desktop/ui/receipt_widget.py`:
            - 保証書テーブルに右クリックメニューを追加
            - 「商品の追加」メニューアイテムを実装
            - 選択行の種別〜店舗コード（列1〜6）をコピーして新しい行を追加
            - SKU・商品名は空欄でプルダウンを設定、保証期間(日)は空欄、保証最終日は日付をデフォルトに設定
    - **レシート管理のクリック動作変更**
        - `python/desktop/ui/receipt_widget.py`:
            - シングルクリックでの画像表示機能を削除
            - ダブルクリックで詳細編集のみを開くように変更（画像ファイル名列も含む）
            - `cellClicked`シグナルの接続を削除
            - `on_receipt_table_cell_clicked`メソッドを削除
- **動作確認:**
    - レシート管理の確定ボタンが正常に動作することを確認
    - 保証書一覧で保証期間と保証最終日が連動することを確認
    - 保証書一覧で右クリック→「商品の追加」で新しい行が追加されることを確認
    - レシート管理でシングルクリックでは何も起こらず、ダブルクリックで詳細編集が開くことを確認
- **効果:**
    - 1枚の保証書に複数商品がある場合に対応可能に
    - 保証期間と保証最終日の入力が容易に
    - レシート管理の操作がシンプルに

---

## 2025-02-XX: テキスト編集時の文字の重複表示問題を修正

- **タスク:** アプリ内で文章等を編集しようとすると文字が2重になって見えなくなる問題を修正
- **状況:** 完了
- **作業時間:** 約1時間
- **詳細:**
    - `python/desktop/ui/condition_template_widget.py`
        - `ConditionTextEdit`クラスで`QTextEdit`から`QPlainTextEdit`に変更
        - `QPlainTextEdit`はよりシンプルで、文字の重複表示問題が発生しにくい
        - フォント設定を明示的に指定（font-family: "Segoe UI", font-size: 9pt, font-weight: normal）
        - スタイルシートを直接設定し、背景色を`rgba`ではなく`rgb`で指定（重複描画を防ぐ）
        - ドキュメントのマージンを0に設定
        - `setAcceptRichText()`の呼び出しを削除（QPlainTextEditには存在しないメソッド）
    - `python/desktop/ui/styles.qss`
        - `QLineEdit`, `QTextEdit`, `QPlainTextEdit`にフォント設定を追加
        - `font-family: "Segoe UI", "Meiryo", "MS Gothic", sans-serif`
        - `font-size: 9pt`
        - `font-weight: normal`
        - フォーカス時の背景色を`rgba`から`rgb`に変更（重複描画を防ぐ）
        - テーブル内の`QTextEdit`用の特別なスタイルを追加
    - `python/desktop/main.py`
        - アプリケーションレベルのフォント設定で`font-weight: Normal`を明示的に指定
- **動作確認:**
    - コンディション説明テンプレートの編集時に文字が2重にならず、正常に表示されることを確認
- **効果:**
    - テキスト編集時の視認性が大幅に改善
    - 文字の重複表示による編集困難が解消

---

## 2025-11-30: GCS画像アップローダー実装

- **タスク:** Google Cloud Storage (GCS) に画像をアップロードし、公開URLを取得するユーティリティを作成
- **状況:** 完了
- **作業時間:** 約30分
- **詳細:**
    - `python/utils/gcs_uploader.py`
        - `upload_image_to_gcs()` 関数を実装
        - バケット名: `hirio-images-main`
        - サービスアカウントキー: `python/desktop/data/credentials/service_account_key.json`
        - アップロード先パス: `used_items/{YYYYMMDD_HHMMSS}_{元のファイル名}` 形式で自動生成
        - Content-Typeを拡張子から自動判定（JPEG, PNG, GIF, BMP, WebP, TIFF対応）
        - エラーハンドリング（ファイル未存在、認証エラー等）を実装
        - 公開URL（`https://storage.googleapis.com/{BUCKET_NAME}/{destination_blob_name}`）を返却
    - `requirements.txt`
        - `google-cloud-storage` を依存関係に追加
- **動作確認:**
    - テスト画像（`python/scripts/test_image.jpg`）のアップロードに成功
    - 公開URLが正しく生成されることを確認
    - ファイル名に日付プレフィックスと `used_items/` プレフィックスが付与されることを確認
- **使用例:**
    ```python
    from utils.gcs_uploader import upload_image_to_gcs
    public_url = upload_image_to_gcs("path/to/image.jpg")
    # 結果: https://storage.googleapis.com/hirio-images-main/used_items/20251130_170322_image.jpg
    ```

---

## 2025-11-28: ルートサマリーテンプレート生成・読み込みの改善

- **タスク:** テンプレート生成で出発時刻等が固定行に配置され店舗データが抜ける問題を修正、読み込みも行番号指定から文字列検索に変更
- **状況:** 完了
- **作業時間:** 約30分
- **詳細:**
    - `python/desktop/utils/template_generator.py`
        - 出発時刻・帰宅時刻・往路高速代・復路高速代を17行目固定から、店舗データの直後（`4 + len(visit_data_rows)` 行目）に配置するように変更
        - 店舗数に関係なく、店舗データの直後に追加情報が配置されるため、データが抜ける問題を解消
    - `python/desktop/ui/route_summary_widget.py`
        - テンプレート読み込み時のデータ取得を行番号指定（15行目以降）から文字列検索（「出発時刻」「帰宅時刻」「往路高速代」「復路高速代」）に変更
        - A列を1-200行目まで検索し、該当する文字列を見つけた行からB列の値を取得
        - 行番号に依存しないため、テンプレート形式が変わっても確実にデータを取得可能
- **動作確認:**
    - テンプレート生成で店舗データの直後に出発時刻等が配置されることを確認
    - テンプレート読み込みで文字列検索により正しくデータが取得されることを確認
- **効果:**
    - 店舗数が多くても店舗データが抜けなくなる
    - テンプレート形式が変わっても読み込みが安定する

---

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

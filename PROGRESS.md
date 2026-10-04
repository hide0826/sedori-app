# sedori-app 進捗（Cursor 向け）

本体デスクトップ（PySide6）＋事務PWA の詳細。HIRIO 全体の地図は [`C:\HIRIO\PROGRESS.md`](../../PROGRESS.md)。

更新日: 2026-10-04（ルート地図・左パネル／訪問順）

---

## いまの状態

**2026-10-04（ルート地図・左パネル／訪問順）:** 店舗マスタ「ルート地図」の左をダークテーマ（白文字）に統一。ルート一覧・店舗（編集中）・タグ絞り込みを CollapsibleSection＋縦スプリッタにし、畳むとヘッダー高さだけになり余りを他パネルへ配分。左右幅・左3段の高さはドラッグ変更し `QSettings` に保存（畳み状態も記憶）。チェックは枠クリックのみ表示オン／オフ、ルート名ダブルクリックで店舗リスト表示＋地図 fitBounds。店舗リストをドラッグ並べ替え→「訪問順序保存」で `stores.display_order` と最新 `route_summaries` の `store_visit_details.visit_order` を更新し、地図の線順も再描画。反映には **HIRIO 再起動**。

**2026-10-04（店舗マスタ・テキスト貼り付け）:** 店舗一覧の操作に「テキスト貼り付け」を追加。店名を1行ずつ貼ると CSV（Takeout）インポートと同じ処理で未登録店を追加（Mapsで住所・電話・座標、店舗コード自動採番、重複スキップ、HA/HO/OF併設は同ルートへ）。併設のホビーオフ等がハードオフと住所・電話が同じでも別店舗になるよう重複判定を修正。反映には **HIRIO 再起動**。足りないホビーオフは再貼り付けで追加できる（既存ハードオフはスキップ）。

**2026-10-03（巡回Web・店舗備考＋自動保存）:** 撮影・巡回の各店舗カードに、IN/OUT・仕入点数の下へ「備考」を追加。Webテンプレート作成時に店舗マスタ（店舗一覧）の備考を `route.json` の `stores[].notes` として載せ、画面に表示する。スマホで備考を変えて保存（自動保存含む）すると、店舗マスタ `stores.notes`（と custom_fields.notes）も上書き同期。入力フィールドは debounce 約0.7秒で自動 PUT（画面は再描画せずフォーカス維持）。反映には **ルートWeb（:8792）の再起動**。

**2026-10-03（ネット仕入箱）:** 店舗の仕入帳ルートとは別に、ネット仕入用の日付箱を作る（`仕入CSV`／`商品画像`／`証憑スクショ`）。`box_kind=online`・`route_code=NET` の `route.json` を書き、route_web に登録する。ネット仕入の **DB保存** 後に撮影候補（`photo_candidates.json`）を箱へ書き、スマホは既存 https（`https://houseserver.tail0a340c.ts.net/`）の商品撮影画面で撮る（ホームページにネット箱セクション）。証憑専用ボタンは付けない。CSV取込は `仕入CSV/` 内の **任意 `*.csv`**（`StockList_*.csv` 以外のアマサーチ出力も可）。

**2026-10-03（SKU全文編集・即反映）:** 仕入行の編集で SKU 全体を直せる（販売済みはロック）。反映時に仕入DB・商品DB・古物台帳の SKU を同時更新。SKUが変わったときは仕入一覧を `force_full` で再描画し、古物台帳タブも開いていれば再読込（再起動不要）。反映には **一度 HIRIO（と必要ならルートWeb）を再起動**してこのコードを載せる。

**2026-09-27（商品撮影）:** 新品などで写真が不要な商品は、リストを長押しして「画像不要にしますか？」ではいを選ぶと、撮影済みへ「画像不要」バッジ付きで移る。このルートの商品が残らなければ、撮影は終わり。撮影済みの画像不要をタップすると、リストに戻せる。反映にはルートWebの再起動。

**2026-09-26（商品撮影）:** JAN付きの写真は、撮影終了前でも保存と同時に画像DBへ書く。すでに撮った分も画像DBへ入れた。https は Tailscale Serve で有効。スマホは Tailscale をオンにして `https://houseserver.tail0a340c.ts.net/` を開くと、カメラを開いたまま続けて撮れる。縦持ちのまま、保存される写真は中央の横長（4:3）だけ。`http://houseserver:8792` は1枚ずつ。操作は Windows ユーザー hide に戻した。

**2026-09-26（商品撮影・画面）:** 候補は仕入DBの最新スナップショット。撮影終了は商品を選ぶと押せる（写真が1枚あると緑）。押すと選択が外れ、その商品は「撮影済み」ページへ移り、選ぶ一覧からは消える。撮影済みをタップすると「再撮影しますか？」と聞き、はいなら写真を消して選び直す画面に戻る。選んだ商品のボタンは緑になる。JANが仕入DBに無い商品は ASIN で写真を紐付ける。反映にはルートWebの再起動。

**2026-09-26（Notion）:** 仕様書ページへの追記はやめる。開くだけでトークン消費が大きい。方針と進捗は `C:\HIRIO\PROGRESS.md` とこのファイル、`docs/specs/` に書く。

**2026-09-26（整理）:** 枝 `feature/sp-api` に push 済み。`244a26a` 欠品チェック時は詳細説明の文だけ。`6d423f8` ルート保険（Excel と空の仕入CSVだけ。仕入帳は上げない）。手元の残りは、HIRIO を一度閉じて開くこと、ドライブの同期を `D:\せどり総合\店舗せどり仕入リスト入れ\ルート保険` だけにすること。ネット仕入の SKU に `MERCARI` や `YAAU` を入れるときは、設定のフリマコードで名称を仕入先（メルカリ、ヤフオク）に合わせ、接頭辞にその文字を書く。

**2026-09-25（欠品チェック時の説明）:** 行の編集で「取説欠品」などにチェックを入れて「コンディション説明呼び出し」を押すと、良い・非常に良い・可のテンプレートは足さない。詳細説明に保存した文だけを入れる。チェックが無いときは、これまでどおりコンディションのテンプレート。反映には HIRIO を一度閉じてもう一度開く。

**2026-09-25（ルート保険）:** 仕入帳はドライブに上げない（約23GB）。Webテンプレ作成時に Excel と空の `仕入CSV` だけ `D:\せどり総合\店舗せどり仕入リスト入れ\ルート保険\日付＋ルート名` へコピーする。ドライブアプリはこのフォルダだけミラーリングする。帰宅後のルート箱取込は、仕入帳の箱を選ぶとルート保険側の新しい CSV と Excel を読む。反映には HIRIO を一度閉じてもう一度開く。rclone は送らない。

**2026-09-25（行の編集のユーザー名）:** OKを押すと、画像がある行は OCR がもう一度走り、その完了通知がユーザー名を上書きしていた。`row_edit_dialog.py` の OK では通知を切ってから読み、空欄だけ埋める。配送表示に「サイズ」「厚さ」「重さ」「kg以内」「cm以内」を追加し、「サイズ:厚さ7cm以内重さ2kg以内」はユーザー名にしない。反映には HIRIO を一度閉じてもう一度開く。

**2026-09-25（夜の再起動が戻らない）:** 9/25 3:00 の再起動は記録上実行済みだが、朝から本体が落ちたまま。`nightly_restart_done=2026-09-25`。待ちの PowerShell が HIRIO と同じコンソールに付いていて、終了で一緒に消えていた。`schedule_relaunch_after_exit` を `DETACHED_PROCESS` で切り離し、`python/desktop/logs/nightly_restart.log` に結果を残す。反映には、いま開いている HIRIO を一度閉じてもう一度開く。バックアップ先 `Z:\HIRIObackup` は現在見えていない（最終成功は 9/23 16:31）。

**2026-09-23（情報撮影）:** ネット仕入の「情報撮影」は、いま開いているログイン済みChromeでメルカリを3枚撮る。拡張 `python/desktop/mercari_capture_extension`（表示名「HIRIO メルカリ撮影」1.0.2）を一度読み込む。撮影はゆっくり。サムネはダブルクリックで拡大。ユーザー名は「ゆうパケットプラスでお届け」などを飛ばす。行の編集で直したユーザー名・取引ID・出品URLは、OKを押しても空欄のときだけ画像の読み取りで埋める。反映には HIRIO 再起動。拡張の中身を変えたあとは chrome://extensions で再読み込み。ヤフオクは未対応。

**2026-09-23（仕入チャネル）:** ネット仕入の仕入チャネルは、CSVの「仕入れ先」から入れる。コメントは見ない。反映には HIRIO 再起動。

**2026-09-23（夜の再起動）:** データバックアップで「毎日、夜中に一度終了して起動し直す」を追加。初期値は毎日 03:00（その時刻から3時間、PCが起きていれば1回）。終了時バックアップがオンなら、閉じるときに ZIP を作ってから起動し直す。反映には HIRIO 再起動。

**2026-09-23（ストック）:** 仕入データとネット仕入の「統合保存／統合読込」を「ストック保存／ストック読込」に変更。保存はルート名＋仕入一覧＋ルート情報。読込は商品を選んで、いま開いている一覧のうしろに追加する（ルート情報は上書きしない）。反映には HIRIO 再起動。

**2026-09-23（ネット仕入のCSV）:** ネット仕入タブに「ルート箱からCSV取込」。仕入CSVだけ読み、ルート情報・画像・レシートは開かない。店舗の仕入データタブの「ルート箱から取込」はそのまま。反映には HIRIO 再起動。

**2026-09-23（ルート箱取込）:** 仕入データの「ルート箱から取込」でルート情報も開く。時刻・メモ・高速代・仕入点数がある `route.json` を優先。店名だけの JSON や空の JSON は Excel のルートテンプレを開く。反映には HIRIO 再起動が必要。

**2026-09-23（ルート一覧の番人）:** `:8792` が落ちたら `python/route_web/watch.ps1` が約15秒で起動し直す。タスク `HIRIO_route_web`（ログオン時・起動2分後・5分おき）。再起動後は watcher の `HIRIO_boot_recover` もこの番人を起こす。`houseserver` は IPv6 が先に返るので、待ち受けは IPv4 と IPv6 の両方。ホーム画面アイコンは `static/icon.png`（表示名「ルート巡回」）。ログ `python/route_web/logs/route_web_watchdog.log`。

**2026-09-23（先読み・撮影分離）:** 巡回Webは時刻とレシートだけ。商品撮影は `/route/{web_id}/photos`（仕入保存後）。「事前処理」はレシートをリネームせずOCRし、2回目は読み直さない。ルート箱取込は、入力がある `route.json` を Excel より優先する。確定した商品JANは画像DBに先に書き、スキャンはバーコードを読まない。サンドボックス `20260919鎌倉ルートサンドボックス` で、本番鎌倉ルートをコピーして確認（本番フォルダは未変更）。仕入の保存とプライスター送信は自動テストしていない。

**2026-09-22（rclone安定化）:** Drive は Google Drive デスクトップの常時同期不要。Webテンプレ作成後に **バックグラウンドで `rclone copy`**（mkdir 省略・フォルダは copy が作る）。GUI から rclone を探す（WinGet Links／フルパス）。地図埋め込み失敗時は「ブラウザで開く」案内。ホワイトアウト対策済。`config/rclone_route_drive.json` はローカルのみ（gitignore）。

**2026-09-22（現場ルートWeb）:** CSV は Drive 直送が正。Webテンプレで **Excel 同時生成**＋**rclone で Drive 上に箱作成**（未設定時スキップ）。1.5b 見送り。枝 `feature/sp-api`。仕様 [`field_route_web_spec.md`](docs/specs/field_route_web_spec.md)。

**2026-09-22（証憑OCR）:** ミニPCで全件OCRを実機確認。一覧に10件前後が載り、BOOK OFF 等は日付・合計まで入る。Tesseract は動作。日本語レシートは精度が低い行あり（Gemini API 設定で改善可）。一括マッチング以降はユーザー確認済み。

**2026-09-21 夜（証憑OCR）:** 全件OCRが処理せず完了していた。ミニPCに Tesseract 本体と日本語データが無く、失敗を黙って飛ばしていた。導入して開始前点検を入れた。

**方針転換（2026-09-21）:** このリポジトリの**実装をミニPCに置き、開発も日常運用もここで行う。**  
理由: `C:\HIRIO` にある watcher / store-cam / judgment / shared などの資産を、同じワークスペースで使いながらシームレスに進めるため。全体Web化の完了は待たない。

**2026-09-21 夜（画像管理）:** スキャンのJAN照合・複数選択・仕入DB候補紐付けを直した。**中央で選んだ画像だけ**別商品へ付け替える。反映には HIRIO 再起動が必要。

- ブランチ: **`feature/sp-api`**（旧作業枝 `feature/route-web-template` はマージ済・同コミット）
- 起動: `start_hirio.bat` または `.venv\Scripts\python.exe python\desktop\main.py`
- ルート時刻Web: 番人 `python\route_web\watch.ps1`（`:8792`。落ちたら起動し直す）。手動は `start_route_web.bat`
- Python: 3.13.15 / venv はこのマシンで作り直し済み
- FastAPI: デスクトップ起動時に自動起動（失敗しても仕入画面は動く）

---

---

---

## 2026-10-04 ルート地図・左パネルと訪問順編集

ルート地図を現場で触りやすいUIにし、周回順を地図から直せるようにした。

### 動き

1. 左パネルはルート／店舗／タグの3段。見出しクリックで畳む／開く。畳むと他段が高さを受け取る
2. 左と地図のあいだ、左3段のあいだの区切り線をドラッグ → 幅・高さを変更。次回起動でも同じ
3. チェック枠: 地図への表示オン／オフ。ルート名ダブルクリック: 店舗一覧表示＋地図拡大
4. 店舗をドラッグ並べ替え → 「訪問順序保存」→ マスタ表示順＋最新ルート登録の訪問順を更新

### 追加・変更

| 何 | 場所 |
|----|------|
| 折りたたみセクション | `python/desktop/ui/store_master/collapsible_section.py`（新規） |
| 地図左パネル・訪問順・サイズ保存 | `python/desktop/ui/store_master/route_map_widget.py` |
| 地図からのルート変更を一覧・カンバン同期 | `python/desktop/ui/store_master/widget.py` |
| 最新サマリー取得・訪問順更新 | `python/desktop/database/route_db.py` |

### 確認

1. HIRIO を再起動
2. データベース管理 → 店舗マスタ → ルート地図
3. 左がダーク／白文字か、畳むと他段が広がるか、区切り線のサイズが再起動後も残るか
4. ルート名ダブルクリック → 店舗並べ替え → 訪問順序保存 → 地図の線順と店舗一覧の並び


## 2026-10-04 店舗マスタ・テキスト貼り付け取込

店舗名リストをメモ帳などから貼り付けて、CSVインポートと同じ流れで取り込む。

### 動き

1. 店舗一覧「テキスト貼り付け」→ ダイアログに店名を1行ずつ貼る → 取り込み開始
2. 空行と `#` 行は無視。CSV／テキスト共通で `import_takeout_places`
3. DBに無い店だけ追加。原則未所属。HA/HO/OF が 80m 以内なら既存と同ルート
4. **修正:** ハードオフ系の別ブランド併設は、住所・電話・座標が同じでも重複スキップしない

### 追加・変更

| 何 | 場所 |
|----|------|
| ボタン・ダイアログ | `python/desktop/ui/store_master/store_list.py` |
| テキスト解析・共通取込・併設重複例外 | `python/desktop/services/google_takeout_favorites_import.py` |
| テスト | `python/desktop/tests/test_google_takeout_favorites_import.py` |

### 確認（実機）

1. HIRIO を再起動
2. テキスト貼り付けで `ホビーオフ 埼玉東松山店` / `ホビーオフ 高麗川店` などを取り込む
3. ハードオフと並んでホビーオフが店舗一覧に出るか

### 次の一手

1. 上記の実機確認（併設ホビーオフ追加）

---
## 2026-10-03 巡回Web・店舗備考連携＋自動保存

現場の撮影・巡回画面（`/route/{web_id}`）で、店舗マスタの備考を見ながら追記し、保存忘れを減らす。

### 動き

1. Webテンプレ作成（ルート選択）時、訪問表／店舗マスタの備考が `route.json` の各店 `notes` に入る（既存）
2. 巡回画面の各店カードで、仕入点数の下に備考テキストエリアを表示
3. `GET /api/route/{web_id}` で備考が空なら店舗マスタから補完（古い route.json 向け）
4. `PUT /api/route/{web_id}` で備考が変わった店だけ `StoreDatabase.set_store_notes_by_code` でマスタ上書き
5. 入力／「今の時刻」後に debounce 自動保存（`keepForm` で DOM 再構築しない）。手動「保存」も可

### 追加・変更

| 何 | 場所 |
|----|------|
| 画面・自動保存 | `python/route_web/static/route.html` |
| GET補完・PUT同期 | `python/route_web/app.py` |
| マスタ同期ヘルパー | `python/route_web/store_notes_sync.py`（新規） |
| 仕様 | `docs/specs/field_route_web_spec.md` |

### 確認（実機）

1. ルートWebを再起動（番人 `watch.ps1` / タスク `HIRIO_route_web`、または `start_route_web.bat`）
2. ルート選択で Webテンプレート作成 → スマホで開く
3. 各店に店舗マスタと同じ備考が出るか
4. 備考を追記 → しばらく待つ／または保存 → データベース管理→店舗マスタ→店舗一覧の備考が更新されるか
5. IN時刻を入れて画面を閉じずに再読込 → 消えていないか（自動保存）

### 次の一手

1. ルートWeb再起動後、実機（スマホ）で備考表示・追記・自動保存を確認
2. 店舗一覧を開き直してマスタ備考の反映を確認

---
## 2026-10-03 ネット仕入箱・SKU全文編集

店舗ルート（仕入帳）とは別系統。親フォルダ例: `D:\せどり総合\ネット仕入れリスト`（設定キー `online_purchase/root_dir`、無ければ既定候補）。

### 動き

1. ネット仕入タブで日付箱を1クリック作成 → `YYYY-MM-DD-フリマ` 等＋ `仕入CSV`／`商品画像`／`証憑スクショ`
2. `route.json` に `box_kind=online`・`route_code=NET`。`ensure_online_route_registration` で route_web 登録
3. **DB保存** 後に `write_photo_candidates` → 箱内 `photo_candidates.json`。専用の「スマホ用ボタン」はサイト側に置かない
4. スマホは https でトップ → ネット箱 → `/route/{web_id}/photos`（既存商品撮影UI）
5. CSV取込: `find_stocklist_csv` が `StockList_*.csv` のあと任意 `*.csv` も探す
6. 仕入行の編集: SKU全文編集 → purchases／products／ledger の rename。一覧は SKU変更時フル再描画

### 追加・変更

| 何 | 場所 |
|----|------|
| 箱作成・候補書込 | `python/desktop/services/online_box.py` |
| サーバ側 online 同期 | `python/route_web/online_sync.py` |
| DB保存後の準備 | `python/desktop/ui/inventory/workflow_mixin.py` |
| 設定 | `python/desktop/utils/settings_helper.py`（`online_purchase/*`） |
| CSV任意名 | `python/desktop/services/route_folder_import.py` |
| SKU全文＋台帳同期 | `purchase_row_edit/dialog.py` / `fee_channel_mixin.py` |
| 一覧即反映 | `python/desktop/ui/product/purchase_edit_mixin.py` |
| route_web UI/API | `app.py` / `registry.py` / `route_purchases.py` / `schema.py` / `server_helper.py` / `static/index.html` / `route_photos.html` |
| テスト | `python/desktop/tests/test_online_box.py`（＋ `test_route_web_phase235.py` 追記） |

### 確認コマンド

```text
cd C:\HIRIO\repo\sedori-app.github
.venv\Scripts\python.exe -m pytest python/desktop/tests/test_online_box.py -q
```

### 次の一手（実機）

1. HIRIO とルートWebを一度再起動
2. ネット仕入で箱作成 → CSV投入 → DB保存 → https で候補が出るか
3. 仕入行の編集で SKU を直し「反映」→ 一覧と古物台帳がすぐ変わるか

---

## 2026-09-27 商品撮影（ルート単位）

仕入を保存したあとの `/route/{web_id}/photos` で撮る。店舗は選ばない。画面にはルート名と日付を出す。

### 動き

1. 候補は、そのルートの仕入DB。同じJANが無ければDB全体。それでも無ければ、日付が近いルート（21日以内を優先。無ければ近い順に3ルート）
2. 写真は `{ルート箱}/商品画像/`。ファイル名は `{route_date}-{route_code}-item-{連番}.jpg`
3. JAN付きの写真は、撮影終了を待たずに画像DBへ書く。ASINだけの写真は画像DBのJAN欄には入らない
4. 撮影終了を押すと、その商品は「撮影済み」へ移る。タップすると再撮影を聞き、はいなら写真を消して一覧に戻す
5. 新品など写真が不要な商品は、リストを長押しして「画像不要」。撮影済みへバッジ付きで移る。リストが空ならそのルートの撮影は終わり。撮影済みからタップすると一覧に戻せる
6. スマホは Tailscale をオンにして `https://houseserver.tail0a340c.ts.net/` を開くと、カメラを開いたまま続けて撮れる。縦持ちのまま、保存は中央の横長（4:3）。`http://houseserver:8792` は1枚ずつ

### 追加・変更

| 何 | 場所 |
|----|------|
| 画面 | `python/route_web/static/route_photos.html` / `route_photos_done.html` |
| API | `python/route_web/app.py`（`POST /api/route/{web_id}/products`、確定、画像不要、撮影済み） |
| 保存と確定 | `python/route_web/product_images.py` |
| 候補の探し方 | `python/route_web/route_purchases.py` |
| 画像DBへの先書き | `python/desktop/services/route_product_seed.py` |
| https | `python/route_web/enable_https.ps1`（Tailscale Serve。実行は Tailscale を掴んでいるユーザー） |
| 仕様 | `docs/specs/field_route_web_spec.md` |

反映にはルートWebの再起動。仕様書の Notion ページは更新しない（2026-09-26 の方針）。

---

## 2026-09-23 情報撮影（メルカリ証憑）

ネット仕入で、出品URL（`https://jp.mercari.com/item/m...`）がある行を、ログイン済みの普段のChromeで3枚撮る。新しい空のChromeは使わない（ログインが切れるため）。パスワードは保存しない。

### 動き

1. 行を選んで「情報撮影」（未選択なら、メルカリURLがある行全部）
2. HIRIO が `127.0.0.1:8765` で待ち、いまの Chrome にそのページを開く
3. 拡張が商品の上、説明までスクロール、取引画面の3枚を撮る
4. 証憑フォルダへ保存し、取引IDが空なら入れ、ユーザー名が空か配送表示なら入れ直す
5. ログインを求められたら「続ける／中止」。人がログインしてから続ける

### 追加・変更

| 何 | 場所 |
|----|------|
| ボタン | `python/desktop/ui/inventory/widget.py`（ネット仕入のときだけ） |
| 待ち受けと保存 | `python/desktop/ui/inventory/mercari_capture_mixin.py` |
| 拡張 | `python/desktop/mercari_capture_extension`（manifest 1.0.2） |
| URLの正規化 | `python/desktop/services/mercari_evidence_capture.py` |
| 出品者名 | `python/desktop/services/flea_market_evidence_ocr.py`（配送表示を飛ばす） |
| サムネ拡大 | `python/desktop/ui/inventory/flea_evidence_panel.py` |
| 手入力を残す | `python/desktop/ui/inventory/row_edit_dialog.py`（OK時は OCR 通知を切る。空欄だけ埋める。「取引画面をOCRして入力」は上書き） |

### 使う前

1. HIRIO を終了して起動し直す
2. `chrome://extensions` で「HIRIO メルカリ撮影」を読み込む（更新したあとは再読み込み。サイトへのアクセスを許可）
3. 出品URLが空の行は撮らない

### 試験

- ログイン済みChromeで3枚保存できた（商品・説明・取引画面）
- 出品者「よう」の前に「ゆうパケットプラスでお届け」があっても、読み取りは「よう」
- 行の編集でユーザー名を直してOKすると、その名前が残る（2026-09-25: OK時の再OCRが上書きしていたのを止めた。再起動後に画面で確認）
- 「サイズ:厚さ7cm以内重さ2kg以内」は出品者名にしない（テストで「よう」になることを確認）

---

## 2026-09-23 ルート一覧の番人とアイコン

### 追加・変更

| 何 | 場所 |
|----|------|
| 番人 | `python/route_web/watch.ps1`（15秒ごとに 8792 を見る） |
| タスク | `HIRIO_route_web`（ログオン・起動2分後・5分おき）。登録は `watch.ps1 -Install` |
| 再起動後 | watcher の `hirio_boot_recover.ps1` がこの番人も起こす |
| 待ち受け | `app.py` の `main()` が IPv4 と IPv6 の両方で 8792 を待つ（`houseserver` は IPv6 が先） |
| アイコン | `python/route_web/static/icon.png`（表示名「ルート巡回」） |
| ログ | `python/route_web/logs/`（gitignore） |

### 試験

- プロセスを止めると、約9秒後に `http://127.0.0.1:8792/health` が戻った
- `http://houseserver:8792/health` は IPv4 と IPv6 の両方で 200
- `/icon.png` `/apple-touch-icon.png` `/manifest.webmanifest` が 200
- スマホのホームに既にある場合は、一度外して追加し直すとアイコンが変わる

---

## パス（このマシン）

| 何 | 場所 |
|----|------|
| リポジトリ | `C:\HIRIO\repo\sedori-app.github` |
| 起動 | `start_hirio.bat` または `.venv\Scripts\python.exe python\desktop\main.py` |
| 本番DB | `python\desktop\data`（`hirio.db` / `hirio_product_purchase.db` / `hirio_inventory_route.db` など） |
| 設定 | `config` |
| 画像・CSV | `D:\せどり総合`（USB SSD。パス置換しない） |
| NASバックアップ | `Z:`（HIRIOから直接開かない） |
| 直下の `data` | 本番DBではない |

---

## 2026-09-21 夜にやったこと（証憑・全件OCR）

### 症状

証憑管理 → レシート・領収書・保証書 でフォルダ選択して全件OCRすると、**中身を読まずに完了**していた。

### 原因（ミニPC移植）

1. **Tesseract OCR 本体が未導入**（`pytesseract` だけ入っていて `tesseract.exe` が無い）
2. 入れた直後は **日本語データ `jpn.traineddata` も無かった**（英語だけ）
3. 全件OCRは失敗してもダイアログを出さず次へ進み、最後に「完了」と出していた
4. Windows 版 Tesseract は `TESSDATA_PREFIX` を tessdata **フォルダ自体**にする（親フォルダだと言語を読めない）

### このPCに入れたもの

| 何 | 場所 |
|----|------|
| Tesseract 5.4.0 | `C:\Program Files\Tesseract-OCR\tesseract.exe` |
| 日本語（tessdata_fast） | 同じ `tessdata\jpn.traineddata` |
| 予備コピー | `C:\HIRIO\tools\tessdata` |
| pillow-heif | venv（iPhone の HEIC 用） |

### コードの直し

| ファイル | 役割 |
|----------|------|
| `python/desktop/utils/ocr_runtime.py` | exe / tessdata 自動検出、画像収集、日本語データ補完 |
| `python/desktop/services/ocr_service.py` | 開始前点検、無効な前PCパスを捨てる |
| `python/desktop/ui/receipt/ocr_mixin.py` | 失敗を隠さない。進捗ラベル。HEIC対応 |
| `python/desktop/ui/receipt/support.py` | QThread の `finished` 衝突を回避（`result_ready`） |
| `python/desktop/utils/image_processor.py` | 長辺1920へ縮小（ミニPCのメモリ対策） |
| `python/desktop/services/receipt_service.py` | 保存先を `python/desktop/data/receipts` に修正 |

### 試験

```
ok collect_top / collect_recursive / prefix / limit
ok smoke_ocr_digits  → TOTAL 1234 を Tesseract が読めた
ok receipt parse tests
```

**2026-09-22 実機:** フォルダ選択→全件OCR OK。レシート一覧に反映。一部は日付・合計が空（OCR精度）。

### 次（実機）

1. **一括マッチング** → 手動調整 → 一括リネーム → GCS → 確定
2. 精度を上げたい行は設定の **Gemini APIキー** を入れる（レシート解析は Gemini 優先）

---

## 2026-09-21 夜にやったこと（画像管理・FastAPI）

### 症状と直し

1. **スキャンが仕入JANに紐付かない**  
   ミニPCに Java / pyzbar が無く、バーコードが読めなかった。  
   → `zxing-cpp`（Java不要）を優先。`requirements.txt` に追加。

2. **スキャン中に RecursionError**  
   Qt の `eventFilter` が再入していた。  
   → `python/desktop/utils/event_filter_safety.py` でガード。

3. **Ctrl 複数選択が重い**  
   選択のたびに一覧を作り直していた。  
   → 選択ロジックを軽くした（`compute_image_multi_select`）。

4. **仕入DB候補が今のJANしか出ない**  
   → 撮影日時±7日の他JANも出し、今のJANを先頭にする。

5. **選んだ写真だけでなく JANグループ全部が別商品に付く**  
   → 中央リストの選択画像だけ `update_image_paths_for_jan` / `assign_image_to_jan`。  
   元の仕入レコードからはそのパスを外す。  
   左ツリーのJANグループ右クリックは、今までどおりグループ全体。

6. **FastAPI**  
   起動時に静かに自動起動。閉じるときは確認ダイアログを出さない。

### 主なファイル

| ファイル | 役割 |
|----------|------|
| `python/desktop/services/image_service.py` | zxing-cpp でJAN読取 |
| `python/desktop/ui/image_manager/scan_mixin.py` | スキャン時の安全化 |
| `python/desktop/ui/image_manager/purchase_link_mixin.py` | 選択画像だけ紐付け |
| `python/desktop/ui/image_manager/support.py` | `resolve_link_image_paths` |
| `python/desktop/ui/product/purchase_edit_mixin.py` | 候補マージ＋旧レコードからパス解除 |
| `python/desktop/ui/main_window.py` | FastAPI 自動起動 |
| `python/desktop/utils/event_filter_safety.py` | eventFilter 再入防止 |
| `requirements.txt` | `zxing-cpp` |

### 試験

venv に pytest は無いので関数を直接実行。

```
ok test_resolve_link_image_paths_uses_selected_subset
ok test_resolve_link_image_paths_falls_back_to_group_when_empty
ok test_remove_image_paths_leaves_other_sku_images
ok test_merge_keeps_other_jans_and_puts_current_first
```

複数選択・eventFilter・zxing-cpp 名のテストも同系統。

実機（選んだ写真だけ別商品へ移る）は **HIRIO 再起動後**に確認。古いプロセスのままでは直っていない。

### 次（実機）

1. 今動いている HIRIO を閉じて `start_hirio.bat` で開き直す
2. 画像管理で JANグループを開き、中央で数枚だけ選ぶ（緑枠）
3. **仕入DB候補紐付け** → 別商品を選ぶ
4. 選んだ枚数だけ新しいJANグループ／仕入レコードへ移り、残りは元のグループに残ること
5. 左のJANグループを右クリックしたときは、グループ全体の紐付けのままであること

---

## 2026-09-21 午後にやったこと（環境）

1. `feature/sp-api` を `git pull`（進捗ログ取り込み含む）
2. Python 3.13 が無かったので winget で 3.13.15 を導入
3. 壊れた `.venv`（メインPCの Python313 を指していた）を `.venv_old` にリネーム
4. `py -3.13 -m venv .venv` → pip → 依存関係導入
   - `PySide6-WebEngine` という独立パッケージは無い → `PySide6`（Addons に WebEngine 含む）を入れた
   - `google-generativeai` は他 Google 系と同時解決すると止まるので、あとから単独インストール
5. HIRIO 画面起動。仕入DB表示OK。`start_hirio.bat` 作成（デスクトップショートカットからも起動可）

---

## 2026-09-22 現場ルートWeb Phase 1

### 追加したもの

| 何 | 場所 |
|----|------|
| 仕様書 | `docs/specs/field_route_web_spec.md` |
| 時刻Web | `python/route_web/`（`:8792`） |
| **固定URL** | `http://houseserver:8792/`（一覧。スマホはこれだけブックマーク） |
| 起動 | 番人 `python/route_web/watch.ps1`（タスク `HIRIO_route_web`）。手動は `start_route_web.bat`。Webテンプレ作成時も自動起動 |
| ボタン | ルート選択「テンプレート生成」の右隣「Webテンプレート作成」 |

### 試験

```
ok route_web schema/registry
ok phase1-api-verify（GET/PUT departure_time・HTMLに今の時刻）
```

### ユーザー確認（残り）

1. スマホで **一度だけ** `http://houseserver:8792/` をブックマーク（Tailscale ON）
2. HIRIO 再起動 → ルート選択で「Webテンプレート作成」
3. 固定URLを開き、日付＋ルート名をタップ →「今の時刻」→ 保存
4. 既存「テンプレート生成」で xlsx が今までどおりできること

---

## 次

1. HIRIO とルートWebを再起動し、巡回画面に商品撮影が無いこと、事前処理、撮影画面を実機で見る
2. 次の仕入で、CSV送信 → 事前処理 → 帰宅後の箱取込 → 照合 → プライスター → 商品撮影
3. 不具合は都度 `feature/sp-api` で修正
4. 証憑管理いじり時: `purchase_item_count` vs アマサーチ件数の差異チェック
5. 1.5b 撮影直後OCRは当面やらない
6. rclone は停止済み。ドライブが同期するのは `ルート保険` だけ。HIRIO 再起動後に Webテンプレ作成で箱ができること、出かける前に同期完了を見ること

---

## 2026-09-22 rclone 安定化（ホワイトアウト対策）

### 症状と対処

| 症状 | 原因 | 対処 |
|------|------|------|
| Drive スキップ | GUI の PATH に rclone 無し | `find_rclone_exe` が WinGet Links／Packages も探す。`rclone_exe` フルパス可 |
| Webテンプレ後に白画面 | UI スレッドで `rclone mkdir`（60s×2）が固まる | **バックグラウンド QThread**＋**mkdir 省略・copy のみ** |
| 地図が真っ黒／切断 | WebEngine 内 Google Maps | 失敗時プレースホルダ＋「ブラウザで開く」案内 |

### 触ったファイル

- `python/desktop/services/rclone_route_drive.py`
- `python/desktop/ui/route_summary/template_mixin.py`（`_RclonePushWorker`）
- `python/desktop/ui/route_summary/map_mixin.py`
- `config/rclone_route_drive.example.json`
- `python/desktop/tests/test_rclone_route_drive.py`

### 運用の理解

- **ローカル仕入帳を Google Drive アプリで常時同期する必要はない**
- HIRIO がテンプレ作成時に **必要な箱だけ rclone で送る**（一方向・そのタイミング）

---

## 2026-09-22 現場ルートWeb Phase 2 / 3 / 5

### 追加

| 何 | 場所 |
|----|------|
| CSV受信箱 | `python/route_web/csv_inbox.py` … `D:\…\仕入CSV_受信` |
| 商品画像 | `python/route_web/product_images.py` |
| API | `python/route_web/app.py` v0.2.0 |
| UI | `python/route_web/static/route.html`（仕入CSV＋商品撮影） |
| ルート箱取込 | `python/desktop/services/route_folder_import.py` + 仕入「ルート箱から取込」 |
| 試験 | `python/desktop/tests/test_route_web_phase235.py` |

### 運用メモ

1. Webテンプレ作成 → ローカル箱＋Excel。**rclone 有効なら裏で Drive にも同じ箱**（完了時ダイアログ）
2. CSV はスマホから Drive の `仕入CSV\` へ直送
3. ミニPC生存時: ルートWebで IN/OUT・レシート・商品撮影
4. ミニPCダウン時: Drive 上の Excel で滞在時刻
5. 帰宅後: 仕入タブ「ルート箱から取込」

rclone 初回: `python\route_web\check_rclone.bat` → example を `config\rclone_route_drive.json` にコピーして enabled（フルパス推奨）

### やらない（確定）

- 1.5b 撮影直後OCR
- スマホのバーコード自動読取（Phase 5 第1弾）
- Tailscale 共有で受信箱パスを固定する運用（技術的に不可）
- rclone mount（配布は **copy のみ**。mkdir は使わない）
- 仕入帳全体のドライブ同期はしない（約23GB）。同期するのは `ルート保険` だけ

---

## やらないこと

- メインPCとミニPCで同じ本番DBを同時に開く
- メインPCの `.venv` を再度コピーする
- `python\desktop\data` を空のDBで上書きする
- SQLite を `Z:` に置く
- `HIRIOold/`・`.bak_phase*`・DBバックアップ・レシートスナップショットを Git に載せない

---

## 一時停止メモ（事務PWA）

- 枝 `feature/server-pwa` / 到達点 `12e3240`（仕入 ルートテンプレ＋DB保存まで）
- 再開時の次手: ⑦古物台帳生成
- 2026-09-21 以降、PWA は後回し。先にミニPC上のデスクトップで開発・運用する

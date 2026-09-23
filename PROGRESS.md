# sedori-app 進捗（Cursor 向け）

本体デスクトップ（PySide6）＋事務PWA の詳細。HIRIO 全体の地図は [`C:\HIRIO\PROGRESS.md`](../../PROGRESS.md)。

更新日: 2026-09-23（夜の再起動）

---

## いまの状態

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
6. （任意）rclone 共有 client_id 廃止（2026）前に自分の Google Cloud クライアントへ切替

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
- Google Drive デスクトップでの常時フォルダ同期（不要）

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

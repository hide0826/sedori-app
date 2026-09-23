# 現場ルートWeb 仕様書（Cursor 横断用）

更新日: 2026-09-23  
リポジトリ: `C:\HIRIO\repo\sedori-app.github`  
作業枝: **`feature/sp-api`**

**いまここ:** Phase 1〜5 実装済。巡回画面は時刻とレシート。商品撮影は仕入保存後の別画面。事前処理はレシートOCRのみ（ファイル名は変えない）。1.5b は見送り。

### サンドボックス（レシート未投入・撮影テスト用）

- フォルダ: `D:\せどり総合\店舗せどり仕入リスト入れ\仕入帳\20260919鎌倉ルートサンドボックス`
  - `レシート画像\` は **空**（手元レシートで撮影保存テスト用）
  - `route.json` … Excel（鎌倉ルート）から店舗名・IN/OUT・出発/帰宅・高速代を投入。`receipt_files` は空配列
- 本番 `20260919鎌倉ルート` は触らない
- `web_id`: `sandbox_20260919_kamakura_empty`
- 直リンク: `http://houseserver:8792/route/sandbox_20260919_kamakura_empty`
- 一覧: `http://houseserver:8792/` → 「鎌倉ルートサンドボックス」
- 画面上は **店舗名＋店舗コード** を表示（`store_name` 入り JSON）

（旧 `_sandbox` コピーやレシート入り試験用 ID は使わない）

### 仕入CSV（Phase 2・運用正）

- **主:** スマホ共有 → **Google Drive** → 当該ルート箱の `仕入CSV\`（フォルダ指定できる）
- **保険:** ルートWebからの直接 Upload／（任意）受信箱 UI
- Tailscale 共有だけではフォルダ指定できないため、受信箱固定運用は主にしない

### ミニPCダウン時の保険

- Webテンプレ作成時に同じ箱へ `route_template_*.xlsx` も生成
- ルート箱を Drive 同期しておけば、落ちている間は **従来どおり Excel で滞在時刻入力**
- Web（:8792）はミニPC上のため、ダウン中は開けない

---

## 1. 目的

店頭〜帰宅後の橋渡し（Google Drive / LINE / Google フォト）を減らし、**ルートフォルダ**を中心にスマホとミニPCをつなぐ。

既存の Excel「テンプレート生成」は残す。横に **Webテンプレート作成** を足し、段階的に置き換える。

---

## 2. いまの運用 → 目指す姿

| 工程 | いま | 目指す姿 |
|------|------|----------|
| ルート時刻 | Excel → Drive → スマホ | **普段:** Web。**保険:** 同箱の Excel（Drive同期・ミニPCダウン時） |
| レシート | Googleフォト → 帰宅後DL → 証憑取込 | 時刻入力と同じ画面で店舗つき撮影 → `レシート画像/` |
| 仕入CSV | アマサーチ → LINE → PC | **Google Drive でルート箱 `仕入CSV/` へ直送**（Web直接Uploadは保険） |
| 取込 | 各タブで個別指定 | ルートフォルダ指定で読込（Phase 3） |
| レシートOCR | 帰宅後に証憑タブ | 撮影後にサーバOCR／Gemini（Phase 1.5b または証憑連携） |
| 商品画像 | Googleフォト → 画像管理 | 撮影時 JAN／直近DB（Phase 5） |

---

## 3. ルートフォルダ規約

```
D:\せどり総合\店舗せどり仕入リスト入れ\仕入帳\
  └── YYYYMMDDルート名\          … Google Drive 同期推奨
        route_template_*.xlsx     … Webテンプレ作成時にも生成（ダウン時の時刻入力保険）
        route.json                … Web時刻・経費（Phase 1）
        商品画像\
        レシート画像\
        仕入CSV\                  … Drive 直送先（Phase 2）
```

- Webテンプレ作成時の起点: **常に** `D:\せどり総合\店舗せどり仕入リスト入れ\仕入帳`（D: がある限りフォルダ選択ダイアログは出さない）
- フォルダ名の禁則文字: `\ / : * ? " < > |` → `_`

### 3.1 `route.json`（schema_version: 1）

時刻・経費・店舗一覧。スマホ「保存」で上書き。

店舗要素に Phase 1.5 で任意追加:

```json
{
  "order": 1,
  "store_code": "HA-01",
  "store_name": "ハードオフ〇〇",
  "in_time": "10:05",
  "out_time": "10:40",
  "purchase_item_count": 12,
  "notes": "",
  "receipt_files": ["2026-09-22-HA-01-01.jpg", "2026-09-22-HA-01-02.jpg"]
}
```

`receipt_files` は `レシート画像/` 内のファイル名（相対）。無くても可。  
`purchase_item_count` は任意（未入力は `null`）。証憑管理でアマサーチ件数との突合用（UIは後回し）。

---

## 4. フェーズ一覧

| Phase | 内容 | 状態 |
|:-----:|------|:----:|
| 0 | 本仕様書 | ✅ |
| 1 | Webテンプレ＋箱＋`route.json`＋時刻Web＋固定一覧URL | ✅ |
| **1.5** | **時刻入力画面でレシート撮影→`レシート画像/` 保存（店舗紐付け）** | ✅ |
| 1.5b | 撮影直後の OCR／Gemini | **見送り**（帰宅後の証憑OCR） |
| **2** | **仕入CSV: Drive 直送 → ルート箱 `仕入CSV/`**（Web Upload／受信箱は保険） | ✅ |
| **3** | **仕入／画像／証憑がルートフォルダ指定で読込** | ✅ |
| 4 | （統合済）旧「別画面でレシート撮影」は **1.5 に吸収** | — |
| **5** | **商品撮影＋任意JAN（手入力）→ `商品画像/`** | ✅（バーコード自動読取は第1弾なし） |

### Phase 1 受け入れ（実績）

- [x] Excel「テンプレート生成」は維持
- [x] Webテンプレで仕入帳配下に日付＋ルート名箱＋商品／レシート／仕入CSV＋`route.json`
- [x] 固定URL `http://houseserver:8792/` 一覧→タップで時刻入力
- [x] 「今の時刻」＋手入力＋保存
- [x] 仕入帳へ自動保存（フォルダ選択ダイアログなし・D: あり時）
- [x] ユーザー実感: 便利（2026-09-22）

---

## 5. Phase 1.5 仕様（時刻入力＋レシート撮影）※今回の変更

### 5.1 ねらい

店にいるときに **IN/OUT を入れる画面のまま** レシートを撮り、帰宅後の Google フォト／手動コピーをやめる。  
店舗はルートテンプレ上の店なので、**撮りながら店舗が確定**している（別画面で店を選び直さない）。

### 5.2 画面イメージ（店舗カードごと）

各店舗ブロック（既存の IN / OUT / 今の時刻）の下に:

| UI | 動作 |
|----|------|
| **仕入点数** | 任意の数値入力（空欄可）。人が数えた仕入商品点数。`stores[].purchase_item_count`（整数 or `null`） |
| **レシートを撮る** | カメラ起動（`<input type="file" accept="image/*" capture="environment">`）。複数枚可 |
| **アルバムから追加** | 同上（capture なし）。フォトから選択可 |
| サムネ一覧 | その店ですでに上がった枚数。削除ボタン（任意・第1弾は削除なしでも可） |

全体の出発／帰宅カードにはレシートボタンは付けない（店舗レシート専用）。

**後回し（証憑管理いじり時）:** この点数とアマサーチ仕入リスト件数の差異チェック。現場Web側は入力＋JSON保存まで。

### 5.3 保存先・ファイル名

- ディレクトリ: `{ルート箱}/レシート画像/`
- ファイル名（証憑管理の既存慣習に寄せる）:
  - `{route_date}-{store_code}-{連番2桁}.jpg`
  - 例: `2026-09-22-HA-01-01.jpg`
  - HEIC の場合はサーバで JPEG 化を試みる（失敗時は `.heic` のまま保存可）
- アップロード成功後、`route.json` の当該店 `receipt_files` にファイル名を追記して保存

### 5.4 API（追加）

| 方法 | パス | 内容 |
|------|------|------|
| `POST` | `/api/route/{web_id}/stores/{store_code}/receipts` | multipart 画像。レスポンスに保存ファイル名 |
| `GET` | `/api/route/{web_id}/receipts/{filename}` | サムネ／確認用（任意） |
| `DELETE` | `/api/route/{web_id}/stores/{store_code}/receipts/{filename}` | 削除（任意・後回し可） |

既存の `PUT /api/route/{web_id}`（時刻保存）は維持。

### 5.5 受け入れ（Phase 1.5）

- [x] 時刻入力ページの各店に「レシートを撮る」「アルバムから」がある
- [x] 画像が当該ルート `レシート画像/` に着く（サンドボックスで POST 確認）
- [x] ファイル名に日付と店舗コード＋連番（例: `2026-09-19-BO-03-02.jpg`）
- [x] 固定URL運用のまま
- [x] サムネ表示（GET receipts）
- [x] 各店「仕入点数」任意入力 → `purchase_item_count` を route.json に保存
- [x] マージ先: `feature/sp-api`（2026-09-22・問題は都度修正方針）
- [ ] スマホ実機でカメラ／アルバムからの追加確認（ユーザー・運用しながら）
- [ ] OCR はまだ無くてよい（1.5b）
- [ ] 証憑管理でのアマサーチ件数との差異確認（後回し）

### 5.6 やらない（Phase 1.5）

- 証憑タブの全件OCR・一括マッチ・GCS・確定の自動起動
- アマサーチ仕入リスト件数 vs `purchase_item_count` の差異UI（証憑管理いじり時）
- 商品画像の撮影（Phase 5）
- Excel 廃止
- 撮影直後OCR（1.5b・任意。本体は証憑管理）

### 5.7 実装メモ（Cursor向け）

- 変更主戦場: `python/route_web/static/route.html` + `python/route_web/app.py` + registry
- 画像はルート箱の絶対パス（`route.json` の `folder_path`）配下へ書く
- Tailscale 経由のアップロードはサイズ制限に注意 → クライアントで長辺縮小（例: 1920）してから POST（store-cam / 証憑OCRと同様）
- 枝: 以降は `feature/sp-api` 上で修正してよい（旧 `feature/route-web-template` はマージ済）

---

## 5b. Phase 2（仕入CSV）

### ねらい

アマサーチの `StockList_*.csv` を、**Google Drive 経由でルート箱の `仕入CSV/` へ直送**する。  
（Tailscale の共有シートではフォルダ指定できないため、受信箱固定は主運用にしない。）

### 操作（正）

1. Webテンプレ作成でルート箱を作る（仕入帳。**Drive 同期推奨**）
2. 店でアマサーチ CSV を共有 → **Google Drive** → その日のルート箱の `仕入CSV\`
3. 帰宅後「ルート箱から取込」またはスタートで読込

### 保険

- ルートWebの「CSVを直接追加」（ミニPCが生きているとき）
- 受信箱 API／UI（任意・副次）

### API（副次・そのまま）

| 方法 | パス | 内容 |
|------|------|------|
| `GET` | `/api/csv-inbox` | 受信箱一覧（任意） |
| `POST` | `/api/route/{web_id}/csv/from-inbox` | 受信箱から移動（任意） |
| `POST` | `/api/route/{web_id}/csv` | multipart 直接保存 |
| `GET` | `/api/route/{web_id}/csv` | ルート箱内 CSV 一覧 |

`route.json` の `csv_files` は任意追記（フォルダ実体が正）。

### Webテンプレ作成時の Excel 保険

- `generate_web_template` が同じ箱に `route_template_{ルート名}_{YYYYMMDD}.xlsx` も生成
- ミニPCダウン中は Web 不可 → **Drive 上の Excel で従来どおり滞在時刻入力**
- 既存の「テンプレート生成」ボタンも残す（単体で Excel だけ作りたいとき用）

### rclone で Drive 上に箱を作成（配布向け・Desktop アプリ不要）

**Google Drive デスクトップの常時同期は不要。** HIRIO がテンプレ作成時だけ送る。

Webテンプレ作成の最後に:

1. ローカル箱を従来どおり作成（route.json / Excel / サブフォルダ）
2. **バックグラウンド**で `rclone copy --create-empty-src-dirs`（UI を止めない）
3. **`rclone mkdir` は使わない**（Drive API で固まりやすい。copy がフォルダを作る）
4. mount は使わない。完了／失敗は別ダイアログ

設定:

- 例: [`config/rclone_route_drive.example.json`](../../config/rclone_route_drive.example.json) → `config/rclone_route_drive.json`
- GUI から見つからないときは `rclone_exe` にフルパス
- または環境変数 `HIRIO_RCLONE_ENABLED=1` / `HIRIO_RCLONE_REMOTE=gdrive`
- 実装: `python/desktop/services/rclone_route_drive.py` ＋ `template_mixin._RclonePushWorker`
- 確認 bat: `python/route_web/check_rclone.bat`
- 未導入・無効時は **スキップ**（ローカル箱作成は成功のまま）

初回準備（1回だけ）:

1. `winget install Rclone.Rclone`（または `tools/rclone/rclone.exe`）
2. `rclone config` で Google Drive リモート作成（例: 名前 `gdrive`）
3. example をコピーして `"enabled": true`

---

## 5c. Phase 3（ルート箱一括取込）

デスクトップ仕入タブ **「ルート箱から取込」**:

| サブフォルダ | 振り分け |
|--------------|----------|
| `仕入CSV/`（無ければ直下 `StockList_*`） | CSV取込 |
| `商品画像/` | 画像管理のカレントフォルダ |
| `レシート画像/` | 証憑 OCR キュー |
| `route_template_*.xlsx` | あればテンプレ読込 |

スタートワークフローの CSV 探索も **`仕入CSV/` 優先**。

実装: `python/desktop/services/route_folder_import.py` + `inventory/workflow_mixin.import_from_route_box`

---

## 5d. Phase 5（商品撮影）

巡回中の各店舗カードには商品撮影を出さない。仕入を保存したあとの別画面で撮る。

- 保存先: `{ルート箱}/商品画像/`
- ファイル名: `{route_date}-{store_code}-item-{連番}.jpg`
- `stores[].product_files`: `[{"file":"…jpg","jan":"…"}]`（jan は任意）
- API: `POST /api/route/{web_id}/stores/{store_code}/products`（form: file + jan）
- バーコード自動読取は、仕入保存後の商品撮影画面で行う（巡回中の画面には出さない）
- 巡回画面: 時刻・仕入点数・レシート。ボタン「事前処理を実行」でレシートOCR（`prep_status.json` と証憑DB。リネームしない）
- 商品撮影: `/route/{web_id}/photos`。JANあり／JANなし。「撮影終了」で `product_files[].confirmed`。仕入レコードの画像列はここでは書き換えない
- 「スキャン実行」は `python/route_web/data/pending_scans.json` に依頼を書く。起動中の HIRIO が確定JANを画像DBへ先に書き、スキャンする
- ルート箱取込は `route.json` があれば Excel より優先

---

## 6. Phase 1 技術詳細（実装済み・要約）

### 6.1 デスクトップ

- `Webテンプレート作成` … `generate_web_template`（**route.json＋保険 Excel＋サブフォルダ**）
- 保存先固定: `D:\せどり総合\店舗せどり仕入リスト入れ\仕入帳`（Drive 同期推奨）
- 既存 `テンプレート生成` … Excel のみ（従来どおり残す）

### 6.2 時刻 Web（:8792）

- 固定URL: `http://houseserver:8792/`
- `route.json` 読み書き

### 6.3 スマホ運用

1. `http://houseserver:8792/` をブックマーク
2. PCで Webテンプレ作成
3. 一覧の日付＋ルートをタップ → 時刻入力（→ Phase 1.5 でレシートも）

---

## 7. ブランチ／マージ方針

- 作業枝: **`feature/sp-api`**
- commit / push 時は全体 PROGRESS・本リポ PROGRESS・（あれば Notion）をセット

| よい | 触らない |
|------|----------|
| `python/route_web/**` | 証憑の確定・GCS本線の自動起動 |
| 仕入「ルート箱から取込」 | 事務 PWA |
| 本仕様・PROGRESS | 撮影直後OCR（1.5b） |

---

## 8. 再開用プロンプト

```
C:\HIRIO\repo\sedori-app.github\docs\specs\field_route_web_spec.md を読んで、
現場ルートWebの不具合修正または次フェーズを進めて。
枝は feature/sp-api。固定URLと既存 Phase 1〜5 を壊さない。
1.5b 撮影直後OCRは見送り。
```

---

## 9. 変更履歴

| 日付 | 内容 |
|------|------|
| 2026-09-23 | 巡回と商品撮影を分離。route.json 優先。レシート先読み。確定JANはスキャンで読み直さない |
| 2026-09-22 | rclone 安定化: 裏送信＋copyのみ（mkdir省略）。GUI PATH／地図埋め込み失敗案内。常時Drive同期は不要 |
| 2026-09-22 | Webテンプレ作成時に rclone で Drive 上へ箱送信（Desktopアプリ不要・未設定時スキップ） |
| 2026-09-22 | CSV は Drive 直送を正に。Webテンプレ作成時に Excel も同時生成（ミニPCダウン時の滞在時刻保険）。受信箱は副次 |
| 2026-09-22 | Phase 2（受信箱→仕入CSV）・Phase 3（ルート箱取込）・Phase 5（商品撮影＋任意JAN）。1.5b は見送り |
| 2026-09-22 | 各店「仕入点数」任意入力 → `purchase_item_count`。アマサーチ差異UIは証憑管理時に後回し |
| 2026-09-22 | Phase 1.5 実装。サンドボックス `sandbox_20260919_kamakura`（本番鎌倉ルートのコピー）でアップロード検証 |
| 2026-09-22 | **仕様変更:** レシート撮影を時刻入力画面に統合（Phase 1.5）。旧 Phase 4 を吸収。OCR は 1.5b |
| 2026-09-22 | Webテンプレ保存先を仕入帳に固定（選択ダイアログ抑制） |
| 2026-09-22 | 固定URL `/` 一覧を追加 |
| 2026-09-22 | 初版。Phase 0〜5 |

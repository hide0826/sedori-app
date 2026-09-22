# 現場ルートWeb 仕様書（Cursor 横断用）

更新日: 2026-09-22  
リポジトリ: `C:\HIRIO\repo\sedori-app.github`  
作業枝: **`feature/sp-api`**（旧 `feature/route-web-template` から 2026-09-22 にマージ済・`b4a7c22`）

**いまここ:** Phase 1＋1.5 は `feature/sp-api` に取り込み済。実運用で問題が出たら都度修正

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

---

## 1. 目的

店頭〜帰宅後の橋渡し（Google Drive / LINE / Google フォト）を減らし、**ルートフォルダ**を中心にスマホとミニPCをつなぐ。

既存の Excel「テンプレート生成」は残す。横に **Webテンプレート作成** を足し、段階的に置き換える。

---

## 2. いまの運用 → 目指す姿

| 工程 | いま | 目指す姿 |
|------|------|----------|
| ルート時刻 | Excel → Drive → スマホ | Web（固定URL一覧→タップ）。今の時刻ボタンあり ✅ |
| レシート | Googleフォト → 帰宅後DL → 証憑取込 | **時刻入力と同じ画面で店舗つき撮影** → `レシート画像/` へ直保存（Phase 1.5） |
| 仕入CSV | アマサーチ → LINE → PC | Tailscale 仮置き → ルート箱へ（Phase 2） |
| 取込 | 各タブで個別指定 | ルートフォルダ指定で読込（Phase 3） |
| レシートOCR | 帰宅後に証憑タブ | 撮影後にサーバOCR／Gemini（Phase 1.5b または証憑連携） |
| 商品画像 | Googleフォト → 画像管理 | 撮影時 JAN／直近DB（Phase 5） |

---

## 3. ルートフォルダ規約

```
D:\せどり総合\店舗せどり仕入リスト入れ\仕入帳\
  └── YYYYMMDDルート名\
        route_template_*.xlsx     … Excel（従来ボタン・任意）
        route.json                … Web時刻・経費（Phase 1）
        商品画像\
        レシート画像\             … Phase 1.5 で Web から直接保存
          YYYY-MM-DD-{店舗コード}-01.jpg
          …
        仕入CSV\                  … Phase 2
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
| **1.5** | **時刻入力画面でレシート撮影→`レシート画像/` 保存（店舗紐付け）** | ✅ API/UI（サンドボックス検証） |
| 1.5b | 撮影直後の OCR／Gemini（総額・時刻・登録番号）→ `route.json` または証憑DB下書き | ⬜ |
| 2 | 仕入CSV仮置き→ルート箱 `仕入CSV/` へ移動 | ⬜ |
| 3 | 仕入／画像／証憑がルートフォルダ指定で読込 | ⬜ |
| 4 | （統合済）旧「別画面でレシート撮影」は **1.5 に吸収** | — |
| 5 | 商品撮影時 JAN／直近DB候補確定 | ⬜ |

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

## 6. Phase 1 技術詳細（実装済み・要約）

### 6.1 デスクトップ

- `Webテンプレート作成` … `generate_web_template`（Excel `generate_template` は触らない）
- 保存先固定: `D:\せどり総合\店舗せどり仕入リスト入れ\仕入帳`

### 6.2 時刻 Web（:8792）

- 固定URL: `http://houseserver:8792/`
- `route.json` 読み書き

### 6.3 スマホ運用

1. `http://houseserver:8792/` をブックマーク
2. PCで Webテンプレ作成
3. 一覧の日付＋ルートをタップ → 時刻入力（→ Phase 1.5 でレシートも）

---

## 7. ブランチ／マージ方針

- ベース: `feature/sp-api`
- 作業枝: `feature/route-web-template`
- Phase 1.5 実機 OK 後、まとめてマージ判断可
- commit / push 時は全体 PROGRESS・本リポ PROGRESS・（あれば Notion）をセット

| よい | 触らない（1.5） |
|------|----------------|
| `python/route_web/**` | 証憑デスクトップの確定・GCS本線 |
| 本仕様・PROGRESS | 事務 PWA |

---

## 8. 再開用プロンプト

```
C:\HIRIO\repo\sedori-app.github\docs\specs\field_route_web_spec.md を読んで、
いまここ（Phase 1.5 時刻入力画面でレシート撮影）を実装して。
枝は feature/route-web-template。固定URLと時刻入力は壊さない。
```

---

## 9. 変更履歴

| 日付 | 内容 |
|------|------|
| 2026-09-22 | 各店「仕入点数」任意入力 → `purchase_item_count`。アマサーチ差異UIは証憑管理時に後回し |
| 2026-09-22 | Phase 1.5 実装。サンドボックス `sandbox_20260919_kamakura`（本番鎌倉ルートのコピー）でアップロード検証 |
| 2026-09-22 | **仕様変更:** レシート撮影を時刻入力画面に統合（Phase 1.5）。旧 Phase 4 を吸収。OCR は 1.5b |
| 2026-09-22 | Webテンプレ保存先を仕入帳に固定（選択ダイアログ抑制） |
| 2026-09-22 | 固定URL `/` 一覧を追加 |
| 2026-09-22 | 初版。Phase 0〜5 |

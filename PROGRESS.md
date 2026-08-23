# sedori-app（HIRIO 本体）進捗ボード

せどり業務デスクトップ＋ FastAPI ＋ PWA の本体リポジトリです。  
HIRIO 全体の正本は [`../../PROGRESS.md`](../../PROGRESS.md)（`C:\HIRIO\PROGRESS.md`）。  
仕様・方針: Notion「[HIRIO サーバー移行・PWA化 仕様書（Cursor向け）](https://app.notion.com/p/3c3a6e81a58b813ebd28e484134d6afe)」  
詳細ログ（デスクトップ寄り）: [`docs/cursor_development_progress.md`](docs/cursor_development_progress.md)

更新日: 2026-08-23

---

## このファイルの使い方

| 知りたいこと | 見る場所 |
|--------------|----------|
| 本体のいま・次・PWA殻 | **このファイル** |
| HIRIO全体 | `C:\HIRIO\PROGRESS.md` |
| デスクトップ機能の細かい履歴 | `docs/cursor_development_progress.md` |
| サーバー／PWA方針 | Notion 仕様書（上記） |

作業が進んだら、このファイルの「いまの状態」「次チャットでやること」「作業ログ」を更新する。  
**チャット終了前:** 触ったら `git commit` & `push`（枝は用途で分ける）。

---

## いまの状態（ひとこと）

**運用・機能更新の正はメインPCデスクトップ。サーバー PWA は主要メニューの読み取り接続がほぼ完了（画像・証憑は未接続）。仕入の時刻突合も PWA から利用可。**

| 項目 | 値 |
|------|-----|
| 運用PC | `D:\HIRIO\repo\sedori-app.github`（機能の正） |
| サーバー | `C:\HIRIO\repo\sedori-app.github`（PWA殻） |
| 機能枝（目安） | `feature/sp-api` など（運用PC） |
| PWA殻枝 | `feature/server-pwa`（origin と同期済み） |
| 最新コミット（殻） | `fbd585c` hirio.db 読み取り一括＋仕入時刻突合 |
| PWA URL | http://192.168.0.200:3000 |
| API URL | http://192.168.0.200:8000 |

---

## 方針（短い版）

1. **本番データは運用PCが正。** サーバーではダミーで機能を試す  
2. **機能実装の正はデスクトップ。** サーバーは当面 PWA ガワ→順に機能載せ  
3. **一気切替しない。** 揃ってから本番接続を別判断  
4. **サブタブ**は親メニューの中に置く（デスクトップと同じ考え方）

---

## 次チャットでやること ※いまここ

1. ~~PWA 殻（左ナビ・主要メニュー）~~ → **完了**
2. ~~価格改定: ダミーCSVプレビュー + LAN API接続~~ → **完了**
3. ~~価格改定サブタブ（改定実行 / 改定ルール / SP-API改定）~~ → **完了**（SP-APIは枠のみ）
4. ~~repo 直下 `PROGRESS.md` 追加~~ → **完了**
5. ~~仕入管理にサブタブ枠（仕入データ / コンディション説明）＋既存CSV整理~~ → **完了**（コンディション説明は枠のみ）
6. ~~価格改定「SP-API改定」をダミー前提で少し中身へ~~ → **完了**（取得〜プレビュー〜反映シミュ。最安追従は未）
7. ~~仕入「コンディション説明」テンプレ編集の薄い中身~~ → **完了**（localStorage → hirio.db API接続へ）
8. ~~他メニュー（ルート / DB / 古物 / 画像 / 証憑 / 分析）は枠のまま → 順に~~ → **完了**（サブタブ＋ダミー表）
9. ~~SP-API「最安追従」のダミー枠中身~~ → **完了**（ダミー計算＋反映シミュ）
10. ~~コンディション説明を hirio.db に接続（第一弾）~~ → **完了**（GET/PUT API、PWAはAPI優先）
11. ~~ルートを hirio.db に接続（読み取り専用）~~ → **完了**（一覧・IN/OUT 表示。PWAはAPI優先）
12. ~~店舗マスタ／商品DBを hirio.db に接続（読み取り専用）~~ → **完了**
13. ~~仕入データの時刻突合~~ → **完了**（PWA からルート選択＋`/api/inventory/match-stores-from-data`、許容1分）
14. ~~ルート訪問DB / 古物 / 分析~~ → **完了**（読み取り専用）
15. **他メニューの本番接続**（候補: **画像** / **証憑**）

### 次チャット向けメモ（2026-08-23 終了時）

- **枝:** `feature/server-pwa`（サーバー作業はこの枝）
- **いま:** hirio.db 読み取り接続は主要メニューほぼ完了。**未接続は画像・証憑のみ**
- **仕入時刻突合:** PWA から利用可。**許容時間デフォルト 1 分**（30分だと誤検知が出やすい）
- **API 一覧（読み取り）:** `/api/routes`, `/api/stores`, `/api/products`, `/api/route-visits`, `/api/ledger/entries`, `/api/analysis/*`
- **API 再起動:** コード更新後は `:8000` の uvicorn を止めてから起動（古いプロセスだと 404）
- **確認 URL:** PWA http://192.168.0.200:3000 / API http://192.168.0.200:8000/docs

1. このファイルの「いまの状態」「次チャットでやること」
2. Notion 仕様書（アクセスURLはページ上部）
3. 枝は `feature/server-pwa`（サーバー作業時）
4. **API はコード更新後に再起動**（`:8000` が古いプロセスのままだと新エンドポイントが 404）

---

## PWA メニュー状況

| メニュー | サブタブ | 状態 |
|----------|----------|------|
| TOP | - | 殻OK |
| 価格改定 | 改定実行 / 改定ルール / SP-API改定 | 実行・ルール利用可。SP-APIは①〜⑤＋最安追従ダミー可 |
| 仕入管理 | 仕入データ / コンディション説明 | 仕入データは CSV＋**時刻突合**＋SKU。コンディション説明は **hirio.db 接続済み** |
| ルート | ルート選択 / ルートサマリー | **hirio.db 接続済み**（読み取り専用・API優先） |
| データベース管理 | 商品DB / 店舗マスタ / ルート訪問DB | **hirio.db 接続済み**（読み取り専用） |
| 古物台帳 | 閲覧・出力 / 入力・生成 | 閲覧は **hirio.db 接続済み**。入力・出力はデスクトップ |
| 画像管理 | 画像管理 / 画像登録 | 薄い版（ダミー表） |
| 証憑管理 | レシート / 経費 / 勘定科目 | 薄い版（ダミー表） |
| 分析 | 基本統計 / 店舗スコア | **hirio.db 接続済み**（簡易集計） |
| 設定 | - | APIベースURL・接続テスト＋DBパス表示 |

---

## 起動メモ（サーバー）

```powershell
# PWA
cd C:\HIRIO\repo\sedori-app.github\pwa
npm run dev -- -H 0.0.0.0 -p 3000

# API（システムの Python 3.12 で起動実績あり。.venv は別ユーザーパスで壊れている場合あり）
cd C:\HIRIO\repo\sedori-app.github\python
python -m uvicorn app:app --host 0.0.0.0 --port 8000

# 確認（トップ / は 404 で正常。health と condition-templates / routes を見る）
# http://192.168.0.200:8000/health
# http://192.168.0.200:8000/api/condition-templates
# http://192.168.0.200:8000/api/routes/summaries
# http://192.168.0.200:8000/api/stores
# http://192.168.0.200:8000/api/route-visits
# http://192.168.0.200:8000/api/ledger/entries
# http://192.168.0.200:8000/api/analysis/summary
# http://192.168.0.200:8000/docs
```

ファイアウォール: TCP 3000 / 8000 受信許可済み（HIRIO PWA 3000 / HIRIO API 8000）。

---

## 作業ログ

### 2026-08-23 ルート訪問DB / 古物台帳 / 分析 hirio.db 接続

- API: `/api/route-visits`, `/api/ledger/entries`, `/api/analysis/summary`, `/api/analysis/store-scores`
- PWA: `DatabaseWorkspace` 訪問タブ、`AntiqueWorkspace`, `AnalysisWorkspace`
- データ件数目安: 訪問450 / 古物1305 / 店舗スコア299

### 2026-08-23 仕入データ 時刻突合（PWA）

- PWA 仕入データ: ルート選択＋許容分数（**デフォルト1分**）＋「時刻突合」ボタン
- API: 既存 `POST /api/inventory/match-stores-from-data` を利用
- 追加: `pwa/src/lib/inventory-api.ts`、`InventoryDataPanel` 拡張

### 2026-08-23 店舗マスタ／商品DB hirio.db 接続（読み取り専用）

- API: `GET /api/stores`, `GET /api/products`（＋各 health）
- PWA: `DatabaseWorkspace` — 店舗検索・商品直近50件。API 優先、不通時ダミー
- ルート訪問DBタブも API 接続済み（後続コミット）
- 追加: `python/routers/stores.py`, `products.py`, `pwa/src/lib/database-api.ts`, `components/database/DatabaseWorkspace.tsx`

### 2026-08-23 ルート hirio.db 接続（読み取り専用）

- API: `GET /api/routes/summaries`, `GET /api/routes/summaries/{id}`, `GET /api/routes/summaries/{id}/visits`, `/api/routes/health`
- PWA: `RouteWorkspace` — ルート一覧・店舗 IN/OUT。API 優先、不通時ダミー
- 追加: `python/routers/routes.py`, `pwa/src/lib/routes-api.ts`, `pwa/src/components/route/RouteWorkspace.tsx`

### 2026-08-23 コンディション説明 hirio.db 接続 確認

- 古い API プロセス停止 → 再起動後、`/health` に db 情報、`/api/condition-templates` が 200
- PWA で「読み込み元: サーバーDB (hirio.db)」表示をメインPCから確認
- 注意: `http://192.168.0.200:8000/` 単体は Not Found（ルート未定義）で正常

### 2026-08-23 コンディション説明 hirio.db 接続（第一弾）

- API: `GET/PUT /api/condition-templates`、リセット、`/health` に DB パス
- PWA: API 優先読み込み、保存時は DB＋localStorage、不通時フォールバック
- 設定: 接続テストで hirio.db パス表示
- コミット: `253db84` / `670e11f`

### 2026-08-23 他メニュー薄い版

- ルート / DB / 古物 / 画像 / 証憑 / 分析にサブタブ＋ダミー表を追加
- 共通: `ThinMenuWorkspace.tsx` / `menuDummyData.ts`
- 本番DB・API未接続（デスクトップが正）
- コミット: `4298fde`

### 2026-08-23 SP-API最安追従ダミー

- SP-API改定タブ下部に最安追従のダミー実行・結果表を追加
- 自動巡回はPWA未対応（表示のみ）
- コミット: `a45d2a1`

### 2026-08-23 コンディション説明 薄い中身

- 仕入「コンディション説明」にデスクトップ相当の薄い編集UI
- 内側タブ: コンディション説明 / 詳細説明（欠品＋カスタム）
- 保存は localStorage のみ（本番 hirio.db 未接続）
- 追加: `ConditionTemplatePanel.tsx` / `conditionTemplates.ts`
- コミット: `6871575`

### 2026-08-23 SP-API改定ダミー中身

- 「SP-API改定」タブにデスクトップ相当の①〜⑤UIを追加（Amazon未接続）
- ダミー取得 → `/repricer/preview|apply` → Amazon反映シミュレーション
- 最安追従は枠＋説明のみ
- ダミーCSVを `dummyRepricerCsv.ts` に共通化
- 追加: `components/repricer/SpApiRepricerPanel.tsx`
- コミット: `babd9db`
- ダミー①〜⑤の流れをメインPCから確認済み（反映はシミュ）

### 2026-08-23 仕入管理サブタブ

- サブタブ「仕入データ」「コンディション説明」（デスクトップと同じ考え方）
- 既存 CSV / SKU / 出品CSV を「仕入データ」へ移設
- ダミー仕入CSVダウンロードを追加（価格改定と同パターン）
- コンディション説明は ComingSoon 枠のみ
- 追加: `components/inventory/InventoryWorkspace.tsx` ほか
- コミット: `da0cff2`

### 2026-08-23 PWA殻〜価格改定ダミー〜PROGRESS

- 枝 `feature/server-pwa` を作成・push（origin 同期済み）
- 左ナビ殻: TOP / 価格改定 / 仕入 / ルート / DB / 古物 / 画像 / 証憑 / 分析 / 設定
- LANから開くとき API を同じホストの `:8000` へ（localhost保存を無視）
- ダミーCSVダウンロード＋プレビュー成功（メインPCから確認）
- 価格改定サブタブ枠を追加
- repo 直下に本 `PROGRESS.md` を追加。全体ボードからもリンク
- コミット: `62bde73` / `db3106f` / `73f25bb` / `2519ac1` / `337fa22`
- **未コミットの意図的除外:** `.bak` / `HIRIOold/` / 領収書スナップショット等（Gitに載せない）

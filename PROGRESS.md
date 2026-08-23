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

**運用・機能更新の正はメインPCデスクトップ。サーバー（mini PC）は PWA 殻＋ダミー検証。価格改定はサブタブ付きでダミーCSVプレビュー成功済み。次は仕入管理のサブタブ整理。**

| 項目 | 値 |
|------|-----|
| 運用PC | `D:\HIRIO\repo\sedori-app.github`（機能の正） |
| サーバー | `C:\HIRIO\repo\sedori-app.github`（PWA殻） |
| 機能枝（目安） | `feature/sp-api` など（運用PC） |
| PWA殻枝 | `feature/server-pwa` |
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
4. **仕入管理にサブタブ枠**（仕入データ / コンディション説明）＋既存CSVを整理
5. 価格改定「SP-API改定」をダミー前提で少し中身へ
6. 他メニュー（ルート / DB / 古物 / 画像 / 証憑 / 分析）は枠のまま → 順に

---

## PWA メニュー状況

| メニュー | サブタブ | 状態 |
|----------|----------|------|
| TOP | - | 殻OK |
| 価格改定 | 改定実行 / 改定ルール / SP-API改定 | 実行・ルール利用可（ダミー）。SP-APIは準備中 |
| 仕入管理 | （これから） | 既存CSVあり。サブタブ未整理 |
| ルート | - | 準備中 |
| データベース管理 | - | 準備中 |
| 古物台帳 | - | 準備中 |
| 画像管理 | - | 準備中 |
| 証憑管理 | - | 準備中 |
| 分析 | - | 準備中 |
| 設定 | - | APIベースURL・接続テストあり |

---

## 起動メモ（サーバー）

```powershell
# PWA
cd C:\HIRIO\repo\sedori-app.github\pwa
npm run dev -- -H 0.0.0.0 -p 3000

# API
cd C:\HIRIO\repo\sedori-app.github\python
python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

ファイアウォール: TCP 3000 / 8000 受信許可済み（HIRIO PWA 3000 / HIRIO API 8000）。

---

## 作業ログ

### 2026-08-23 PWA殻〜価格改定ダミー

- 枝 `feature/server-pwa` を作成・push
- 左ナビ殻: TOP / 価格改定 / 仕入 / ルート / DB / 古物 / 画像 / 証憑 / 分析 / 設定
- LANから開くとき API を同じホストの `:8000` へ（localhost保存を無視）
- ダミーCSVダウンロード＋プレビュー成功（メインPCから確認）
- 価格改定サブタブ枠を追加
- 主要コミット: `62bde73` / `db3106f` / `73f25bb` / `2519ac1`

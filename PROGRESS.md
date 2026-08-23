# sedori-app�E�EIRIO 本体）進捗�EーチE

せどり業務デスクトップ！EFastAPI �E�EPWA の本体リポジトリです、E 
HIRIO 全体�E正本は [`../../PROGRESS.md`](../../PROGRESS.md)�E�EC:\HIRIO\PROGRESS.md`�E�、E 
仕様�E方釁E Notion「[HIRIO サーバ�E移行�EPWA匁E仕様書�E�Eursor向け�E�](https://app.notion.com/p/3c3a6e81a58b813ebd28e484134d6afe)、E 
詳細ログ�E�デスクトップ寁E���E�E [`docs/cursor_development_progress.md`](docs/cursor_development_progress.md)

更新日: 2026-08-23

---

## こ�Eファイルの使ぁE��

| 知りたぁE��と | 見る場所 |
|--------------|----------|
| 本体�EぁE��・次・PWA殻 | **こ�Eファイル** |
| HIRIO全佁E| `C:\HIRIO\PROGRESS.md` |
| チE��クトップ機�Eの細かい履歴 | `docs/cursor_development_progress.md` |
| サーバ�E�E�PWA方釁E| Notion 仕様書�E�上記！E|

作業が進んだら、このファイルの「いまの状態」「次チャチE��でめE��こと」「作業ログ」を更新する、E 
**チャチE��終亁E��:** 触ったら `git commit` & `push`�E�枝は用途で刁E��る）、E

---

## ぁE��の状態（�Eとこと�E�E

**運用・機�E更新の正はメインPCチE��クトップ。サーバ�Eは PWA 殻�E�ダミ�E検証。主要メニューは薁E��中身まで揁E��た。SP-API最安追従もダミ�E可。次は本番接続�E別判断、E*

| 頁E�� | 値 |
|------|-----|
| 運用PC | `D:\HIRIO\repo\sedori-app.github`�E�機�Eの正�E�E|
| サーバ�E | `C:\HIRIO\repo\sedori-app.github`�E�EWA殻�E�E|
| 機�E枝（目安！E| `feature/sp-api` など�E�運用PC�E�E|
| PWA殻极E| `feature/server-pwa`�E�Erigin と同期済み�E�E|
| 最新コミット（殻�E�E| �E�未コミッチE 他メニュー�E�最安追従！E|
| PWA URL | http://192.168.0.200:3000 |
| API URL | http://192.168.0.200:8000 |

---

## 方針（短ぁE���E�E

1. **本番チE�Eタは運用PCが正、E* サーバ�Eではダミ�Eで機�Eを試ぁE 
2. **機�E実裁E�E正はチE��クトップ、E* サーバ�Eは当面 PWA ガワ→頁E��機�E載せ  
3. **一気�E替しなぁE��E* 揁E��てから本番接続を別判断  
4. **サブタチE*は親メニューの中に置く（デスクトップと同じ老E��方�E�E

---

## 次チャチE��でめE��こと ※ぁE��ここ

1. ~~PWA 殻�E�左ナビ・主要メニュー�E�~~ ↁE**完亁E*
2. ~~価格改宁E ダミ�ECSVプレビュー + LAN API接続~~ ↁE**完亁E*
3. ~~価格改定サブタブ（改定実衁E/ 改定ルール / SP-API改定）~~ ↁE**完亁E*�E�EP-APIは枠のみ�E�E
4. ~~repo 直丁E`PROGRESS.md` 追加~~ ↁE**完亁E*
5. ~~仕�E管琁E��サブタブ枠�E�仕�EチE�Eタ / コンチE��ション説明）＋既存CSV整琁E~ ↁE**完亁E*�E�コンチE��ション説明�E枠のみ�E�E
6. ~~価格改定「SP-API改定」をダミ�E前提で少し中身へ~~ ↁE**完亁E*�E�取得〜�Eレビュー〜反映シミュ。最安追従�E未�E�E
7. ~~仕�E「コンチE��ション説明」テンプレ編雁E�E薁E��中身~~ ↁE**完亁E*�E�EocalStorage保存。本番DB未接続！E
8. ~~他メニュー�E�ルーチE/ DB / 古物 / 画僁E/ 証憁E/ 刁E���E��E枠のまま ↁE頁E��~~ ↁE**完亁E*�E�サブタブ＋ダミ�E表�E�E
9. ~~SP-API「最安追従」�Eダミ�E枠中身~~ ↁE**完亁E*�E�ダミ�E計算＋反映シミュ�E�E
10. **吁E��ニューの本番API/DB接続�E別判断**�E�一気�E替しなぁE��E

### 次チャチE��開始時の読み方

1. こ�Eファイルの「いまの状態」「次チャチE��でめE��こと、E
2. Notion 仕様書�E�アクセスURLはペ�Eジ上部�E�E
3. 枝�E `feature/server-pwa`�E�サーバ�E作業時！E

---

## PWA メニュー状況E

| メニュー | サブタチE| 状慁E|
|----------|----------|------|
| TOP | - | 殻OK |
| 価格改宁E| 改定実衁E/ 改定ルール / SP-API改宁E| 実行�Eルール利用可。SP-APIは①〜⑤�E�最安追従ダミ�E可 |
| 仕�E管琁E| 仕�EチE�Eタ / コンチE��ション説昁E| 仕�EチE�Eタ利用可。コンチE��ション説明�E薁E��編雁EI�E�ブラウザ保存�E本番DB未接続！E|
| ルーチE| ルート選抁E/ ルートサマリー | 薁E��版（ダミ�E表�E�E|
| チE�Eタベ�Eス管琁E| 啁E��DB / 店�Eマスタ / ルート訪問DB | 薁E��版（ダミ�E表�E�E|
| 古物台帳 | 閲覧・出劁E/ 入力�E生�E | 薁E��版（ダミ�E表�E�E|
| 画像管琁E| 画像管琁E/ 画像登録 | 薁E��版（ダミ�E表�E�E|
| 証憑管琁E| レシーチE/ 経費 / 勘定科目 | 薁E��版（ダミ�E表�E�E|
| 刁E�� | 基本統訁E/ 店�Eスコア | 薁E��版（ダミ�E表�E�E|
| 設宁E| - | APIベ�EスURL・接続テストあめE|

---

## 起動メモ�E�サーバ�E�E�E

```powershell
# PWA
cd C:\HIRIO\repo\sedori-app.github\pwa
npm run dev -- -H 0.0.0.0 -p 3000

# API�E�シスチE��の Python 3.12 で起動実績あり、Evenv は別ユーザーパスで壊れてぁE��場合あり！E
cd C:\HIRIO\repo\sedori-app.github\python
python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

ファイアウォール: TCP 3000 / 8000 受信許可済み�E�EIRIO PWA 3000 / HIRIO API 8000�E�、E

---

## 作業ログ

### 2026-08-23 他メニュー薁E��牁E

- ルーチE/ DB / 古物 / 画僁E/ 証憁E/ 刁E��にサブタブ＋ダミ�E表を追加
- 共送E `ThinMenuWorkspace.tsx` / `menuDummyData.ts`
- 本番DB・API未接続（デスクトップが正�E�E
- コミッチE `4298fde`

### 2026-08-23 SP-API最安追従ダミ�E

- SP-API改定タブ下部に最安追従�Eダミ�E実行�E結果表を追加
- 自動巡回�EPWA未対応（表示のみ�E�E

### 2026-08-23 コンチE��ション説昁E薁E��中身

- 仕�E「コンチE��ション説明」にチE��クトップ相当�E薁E��編雁EI
- 冁E�EタチE コンチE��ション説昁E/ 詳細説明（欠品E��カスタム�E�E
- 保存�E localStorage のみ�E�本番 hirio.db 未接続！E
- 追加: `ConditionTemplatePanel.tsx` / `conditionTemplates.ts`
- コミッチE `6871575`

### 2026-08-23 SP-API改定ダミ�E中身

- 「SP-API改定」タブにチE��クトップ相当�E①〜⑤UIを追加�E�Emazon未接続！E
- ダミ�E取征EↁE`/repricer/preview|apply` ↁEAmazon反映シミュレーション
- 最安追従�E枠�E�説明�Eみ
- ダミ�ECSVめE`dummyRepricerCsv.ts` に共通化
- 追加: `components/repricer/SpApiRepricerPanel.tsx`
- コミッチE `babd9db`
- ダミ�E①〜⑤の流れをメインPCから確認済み�E�反映はシミュ�E�E

### 2026-08-23 仕�E管琁E��ブタチE

- サブタブ「仕�EチE�Eタ」「コンチE��ション説明」（デスクトップと同じ老E��方�E�E
- 既孁ECSV / SKU / 出品CSV を「仕�EチE�Eタ」へ移設
- ダミ�E仕�ECSVダウンロードを追加�E�価格改定と同パターン�E�E
- コンチE��ション説明�E ComingSoon 枠のみ
- 追加: `components/inventory/InventoryWorkspace.tsx` ほぁE
- コミッチE `da0cff2`

### 2026-08-23 PWA殻〜価格改定ダミ�E〜PROGRESS

- 极E`feature/server-pwa` を作�E・push�E�Erigin 同期済み�E�E
- 左ナビ殻: TOP / 価格改宁E/ 仕�E / ルーチE/ DB / 古物 / 画僁E/ 証憁E/ 刁E�� / 設宁E
- LANから開くとぁEAPI を同じ�Eスト�E `:8000` へ�E�Eocalhost保存を無視！E
- ダミ�ECSVダウンロード＋�Eレビュー成功�E�メインPCから確認！E
- 価格改定サブタブ枠を追加
- repo 直下に本 `PROGRESS.md` を追加。�E体�Eードからもリンク
- コミッチE `62bde73` / `db3106f` / `73f25bb` / `2519ac1` / `337fa22`
- **未コミット�E意図皁E��夁E** `.bak` / `HIRIOold/` / 領収書スナップショチE��等！Eitに載せなぁE��E

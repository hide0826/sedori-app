# sedori-app 進捗（Cursor 向け）

本体デスクトップ（PySide6）＋事務PWA の詳細。HIRIO 全体の地図は [`C:\HIRIO\PROGRESS.md`](../../PROGRESS.md)。

更新日: 2026-09-21

---

## いまの状態

**方針転換（2026-09-21）:** このリポジトリの**実装をミニPCに置き、開発も日常運用もここで行う。**  
理由: `C:\HIRIO` にある watcher / store-cam / judgment / shared などの資産を、同じワークスペースで使いながらシームレスに進めるため。全体Web化の完了は待たない。

- ブランチ: `feature/sp-api`（最新 `0047328` 付近）
- 起動確認済み（ミニPC）: 仕入DB 1422件表示。FastAPI 未接続でも仕入画面は動く
- Python: 3.13.15（`C:\Users\hide\AppData\Local\Programs\Python\Python313\python.exe`）
- venv: このマシンで作り直し済み（メインPCのコピーは `.venv_old` に退避）

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

## 2026-09-21 にやったこと

1. `feature/sp-api` を `git pull`（進捗ログ取り込み含む）
2. Python 3.13 が無かったので winget で 3.13.15 を導入
3. 壊れた `.venv`（メインPCの Python313 を指していた）を `.venv_old` にリネーム
4. `py -3.13 -m venv .venv` → pip → 依存関係導入
   - `PySide6-WebEngine` という独立パッケージは無い → `PySide6`（Addons に WebEngine 含む）を入れた
   - `google-generativeai` は他 Google 系と同時解決すると止まるので、あとから単独インストール
5. HIRIO 画面起動。仕入DB表示OK。`start_hirio.bat` 作成（デスクトップショートカットからも起動可）

---

## 次

1. 日常の仕入・改定はミニPCのこのコピーで行う。**メインPCで同じ DB を開かない**
2. 画像・CSV が要る作業の前に `D:\せどり総合` をミニPCの D: へ（未コピーなら）
3. 価格改定など API が要る機能は、メニュー「ツール → FastAPIサーバー起動」
4. 開発は `C:\HIRIO` ワークスペースのまま（隣の store-cam 等を読んでよい）

---

## やらないこと

- メインPCとミニPCで同じ本番DBを同時に開く
- メインPCの `.venv` を再度コピーする
- `python\desktop\data` を空のDBで上書きする
- SQLite を `Z:` に置く
- 頼まれるまで git commit / push

---

## 一時停止メモ（事務PWA）

- 枝 `feature/server-pwa` / 到達点 `12e3240`（仕入 ルートテンプレ＋DB保存まで）
- 再開時の次手: ⑦古物台帳生成
- 2026-09-21 以降、PWA は後回し。先にミニPC上のデスクトップで開発・運用する

# sedori-app 進捗（Cursor 向け）

本体デスクトップ（PySide6）＋事務PWA の詳細。HIRIO 全体の地図は [`C:\HIRIO\PROGRESS.md`](../../PROGRESS.md)。

更新日: 2026-09-21 夜

---

## いまの状態

**方針転換（2026-09-21）:** このリポジトリの**実装をミニPCに置き、開発も日常運用もここで行う。**  
理由: `C:\HIRIO` にある watcher / store-cam / judgment / shared などの資産を、同じワークスペースで使いながらシームレスに進めるため。全体Web化の完了は待たない。

**2026-09-21 夜（画像管理）:** スキャンのJAN照合・複数選択・仕入DB候補紐付けを直した。**中央で選んだ画像だけ**別商品へ付け替える。反映には HIRIO 再起動が必要。

- ブランチ: `feature/sp-api`
- 起動: `start_hirio.bat` または `.venv\Scripts\python.exe python\desktop\main.py`
- Python: 3.13.15 / venv はこのマシンで作り直し済み
- FastAPI: デスクトップ起動時に自動起動（失敗しても仕入画面は動く）

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

## 次

1. **HIRIO 再起動** → 選んだ写真だけの仕入紐付けを実機確認
2. 日常の仕入・改定はミニPCのこのコピーで行う。**メインPCで同じ DB を開かない**
3. 画像・CSV が要る作業の前に `D:\せどり総合` をミニPCの D: へ（未コピーなら）
4. FastAPI は起動時に自動。ダメならメニュー「ツール → FastAPIサーバー起動」
5. 開発は `C:\HIRIO` ワークスペースのまま（隣の store-cam 等を読んでよい）

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

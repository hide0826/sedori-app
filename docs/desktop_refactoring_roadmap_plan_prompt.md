# デスクトップアプリ リファクタリング道筋 — Plan モード用プロンプト

価格改定リファクタ（Phase 0〜6）完了後の **次の一手** を、おすすめ順に進めるための指示書です。  
Cursor の **Plan モード** に貼り付けて使います。

## 現在地（2026-07-12 更新）

| 項目 | 状態 |
|------|------|
| 価格改定 Phase 0〜6 | **完了** |
| Track A Phase 0〜3（仕入DB） | **完了**（Phase 3: 行編集分割・手動確認 OK） |
| Track B Phase 0〜1（在庫） | **完了**（手動確認 OK） |
| Track X Phase 0〜2 | **完了**（Phase 2: `ensure_desktop_sys_path`・手動確認 OK） |
| Track C Phase 0〜1（レシート） | **完了**（`ui/receipt/` + シム。証憑タブ手動確認 OK） |
| Track D Phase 0〜1（画像管理） | **完了**（`ui/image_manager/`。手動確認は**後回し可**・エラー時に修正） |
| Track E Keepa Phase 0〜1 | **完了**（`services/keepa/`） |
| Track E route_summary Phase 0〜1 | **完了**（`ui/route_summary/`。手動確認は**後回し可**） |
| Track E store_master Phase 0〜1 | **完了**（`ui/store_master/`。手動確認は**後回し可**） |
| **次にやること** | **任意**（purchase_inventory_only / 分割パッケージ path 残置整理 / 価格改定仕上げ 等） |

### 次のチャットでやること（これだけコピーして送る）

おすすめ順の必須トラック＋任意 Track A Phase 3 / Track X Phase 2 は完了。残りは任意。

---

## 使い方（一般）

1. Cursor で **Plan モード** に切り替える
2. この MD を @ 参照し、先頭に **トラック＋Phase** だけ追記して実行する
3. **1 Plan = 1 Phase**。完了・手動確認後に次を投げる
4. 価格改定コア・完了済み Phase は **触れない**（別タスクでない限り）
5. 進捗は本ファイルのチェックリストと `docs/cursor_development_progress.md` を更新する

### おすすめ実行順（全体マップ）

| 順番 | トラック | 内容 | リスク | 目安 |
|------|----------|------|--------|------|
| ① | **Track A** | 仕入DB（`product_widget`）安全網→分割 | 中 | **0〜3 完了**（手動確認 OK） |
| ② | **Track B** | 在庫（`inventory_widget`）安全網→分割 | 中〜高 | **0〜1 完了**（手動確認 OK） |
| ③ | **Track X** | import / DB bootstrap / sys.path | 中〜高 | **Phase 0〜2 完了**（手動確認 OK） |
| ④ | **Track C** | レシート（`receipt_widget`） | 高 | **0〜1 完了**（手動確認 OK） |
| ⑤ | **Track D** | 画像管理（`image_manager_widget`） | 高 | **0〜1 完了**（手動確認は後回し可） |
| ⑥ | **Track E** | Keepa / ルート集計 / 店舗マスタ | 中 | **Keepa・route_summary・store_master 完了**（手動確認は後回し可） |
| — | （任意） | 価格改定の仕上げ / purchase_inventory_only / path 残置整理 | 低 | 必要になったら |

**原則**: 大きい画面ほど「テスト追加 → 小さな整理 → UI 分割」の順。価格改定と同じ進め方。

---

## 完了済み（参考・原則触らない）

### 価格改定
- ドキュメント: `docs/repricer_refactoring_plan_prompt.md`（Phase 0〜6）
- 成果物: `python/tests/test_repricer_weekly.py`、`ui/repricer/`、シム・compat 等

### Track A Phase 0（仕入DB 安全網）
- `desktop/tests/` に purchase_cost_calc / channel_cost / break_even / inventory_only / elapsed / repricing_summary
- 検証: 当時 desktop/tests 73件 + repricer 31件

### Track A Phase 1（product_widget import）
- `_desktop_import_compat.py` 拡張、`product_widget` の ImportError を先頭1ブロックに集約
- UI は `_desktop_ui_compat.py`（循環回避）
- DB の `from database.*` は未整理（**Track X 対象**）

### Track A Phase 2（product_widget 分割）
- `ui/product/`（widget / support / purchase_*_mixin）+ `product_widget.py` シム
- フォロー: 検索時 `NameError: ProductWidget` → `PurchaseTableMixin._receipt_image_lookup_key` に修正
- 手動確認 OK（仕入DB検索含む）

### Track B Phase 0（在庫 安全網）
- `test_inventory_store_matching` / `test_condition_labels` / `test_inventory_jan_normalize` / `test_csv_io_validate`
- `test_purchase_inventory_only` 拡充
- `inventory_widget.py` 本体は未変更だった（当時）

### Track B Phase 1（inventory_widget 分割）
- `ui/inventory/`（widget / support / dialogs×4 / mixins×6）+ `inventory_widget.py` シム
- バックアップ: `inventory_widget.py.bak_phase1`
- 検証: InventoryWidget import OK、desktop/tests **96件**
- 在庫タブ手動確認 OK

### Track X Phase 0（DB bootstrap / db_paths import）
- `database/db_path_resolve.py` にパス解決を集約
- database 18ファイルが相対 import で利用
- `db_paths.py` / `db_bootstrap.py` 本体は未変更
- 検証: desktop/tests **96件**

### Track X Phase 1（settings_widget import）
- `_desktop_import_compat` / `_desktop_ui_compat` に settings 用シンボルを追加
- `settings_widget.py` 先頭1ブロックに集約（挙動・デフォルト値不変）
- 検証: SettingsWidget import OK、desktop/tests **96件**

### Track C Phase 0（レシート安全網）
- `test_receipt_sku_linking` 拡充 + purchase_price_policy / matching_normalize / parse_text
- `receipt_widget.py` 未変更
- 検証: desktop/tests **118件**

### Track C Phase 1（receipt_widget 分割）
- `ui/receipt/`（widget / support / mixins×9）+ `receipt_widget.py` シム
- バックアップ: `receipt_widget.py.bak_phase1`
- フォロー: `receipt_processed` Signal 復元、GCS/`__file__` 階層・スナップショットパス修正
- 検証: ReceiptWidget import OK、desktop/tests **118件**
- 証憑タブ手動確認 OK（全件OCR・GCSアップロード含む）

### Track D Phase 0（画像管理安全網）
- `test_amazon_image_naming.py` 拡充（temp名・空SKU・PT09・path_getter 等）
- `test_image_service.py` 新規（JAN抽出・group_by_jan・プリセット・保存形式・自動補正サイズ）
- ウィジェット先頭ヘルパーの直接テストは見送り（`python/utils` と `desktop/utils` の import 衝突。分割時に再挑戦）
- `image_manager_widget.py` 未変更
- 検証: desktop/tests **134件**

### Track D Phase 1（image_manager_widget 分割）
- `ui/image_manager/`（widget / support / mixins×9）+ `image_manager_widget.py` シム
- バックアップ: `image_manager_widget.py.bak_phase1`
- Signal `_preview_image_ready` / `_preview_image_error` を widget に維持
- `__file__` 階層補正（snapshot / config / GCS / amazon loader / ListingLoader）
- `@staticmethod` `_pil_image_to_qpixmap` 維持
- 検証: ImageManagerWidget import OK、desktop/tests **134件**
- **残作業**: 画像管理タブ手動確認は**後回し可**（エラー時に修正）

### Track E Phase 0（Keepa 安全網）
- `test_keepa_service.py` 新規（10件）
- `keepa_service.py` 未変更（当時）
- 検証: desktop/tests **144件**

### Track E Phase 1（keepa_service 分割）
- `services/keepa/`（models / price_helpers / offer_helpers / analysis_369 / service）+ Mixin 束ね
- `keepa_service.py` 後方互換シム
- バックアップ: `keepa_service.py.bak_phase1`
- 自己参照: `KeepaService._offer_csv_numbers` → `KeepaOfferHelpersMixin._offer_csv_numbers`（モジュール分割後の NameError 防止）
- 検証: KeepaService import OK、desktop/tests **144件**

### Track E route_summary Phase 0（安全網）
- `test_route_summary_helpers` / `test_route_template_time_validation` / `test_route_visit_normalize`（計11件）
- `_source_symbol_loader` で AST 抽出（utils 衝突回避）
- ウィジェット本体未変更（当時）
- 検証: desktop/tests **155件**

### Track E route_summary Phase 1（分割）
- `ui/route_summary/` + シム、`data_saved` / `__file__` 階層維持
- 検証: desktop/tests **155件**

### Track E store_master Phase 0（安全網）
- `test_store_master_helpers.py`（9件）— 座標 coerce / 座標有無 / プラットフォーム・フリマトークン提案 / `_normalize_entries`
- `_source_symbol_loader` で AST 抽出（ウィジェット本体未変更）
- 検証: desktop/tests **164件**

### Track E store_master Phase 1（分割）
- `ui/store_master/`（widget / support / store_dialogs / route_dialogs / store_list / expense / online / flea_users）+ シム
- バックアップ: `store_master_widget.py.bak_phase1`
- `sys.path`=`../..`、Maps import を `support.py` に集約、`@staticmethod` 維持
- Phase 0 テストのソースパスを分割先へ更新
- 検証: StoreMasterWidget import OK、desktop/tests **164件**

### 分割時の教訓（次の UI / サービス分割でも守る）
- コピペ移動のみ。ロジック変更禁止
- `@staticmethod` / `@contextmanager` のデコレータ行を落とさない
- **クラス属性の Signal も忘れず widget.py に残す**（メソッド抽出だけだと欠落する）
- **`__file__` 相対パスはディレクトリ階層が変わる**（`ui/foo/` 化で `../..` の指す先がずれる。3階層・候補複数で防御）
- クラス自己参照（`Foo.bar`）は移動先クラス名へ置換（NameError 防止）
- mixin 同士は import しない。`widget.py` だけが束ねる
- 後方互換シムを旧パスに残す（`main_window` / 既存 `from services.xxx` 変更不要）
- **サービス分割でも旧モジュールパスのシム必須**（例: `keepa_service.py` → `services/keepa/`）

---

## Plan モードに貼り付けるプロンプト

```
# タスク: HIRIO デスクトップアプリの慎重なリファクタリング（道筋に沿って 1 Phase ずつ）

## 背景

中古せどり業務自動化システム「HIRIO」の PySide6 デスクトップアプリをリファクタリングする。
価格改定まわり（docs/repricer_refactoring_plan_prompt.md Phase 0〜6）は完了済み。
Track A Phase 0〜2（仕入DB テスト・import・ui/product 分割）完了済み。
Track B Phase 0〜1（在庫 テスト・ui/inventory 分割）完了済み（手動確認 OK）。
Track C Phase 0〜1（レシート安全網・ui/receipt 分割）完了済み（手動確認 OK・Signal/GCSパス修正済）。
Track D Phase 0（画像管理安全網）完了済み。
Track D Phase 1（`ui/image_manager/` 分割）完了済み（手動確認は後回し可）。
Track E Keepa Phase 0〜1（安全網・`services/keepa/` 分割）完了済み。
Track E store_master Phase 0〜1（安全網・`ui/store_master/` 分割）完了済み（手動確認は後回し可）。
Track A Phase 3（行編集ダイアログ分割）完了済み（手動確認 OK）。
本番運用中のため、**挙動を変えずに**コード整理・テスト追加のみ行う。

関連ドキュメント:
- docs/desktop_refactoring_roadmap_plan_prompt.md（本道筋・進捗の正）
- docs/cursor_development_progress.md（実装ログ）
- docs/repricer_refactoring_plan_prompt.md（価格改定・完了済み）
- D:\HIRIO\docs\pyside6_desktop_app_specification.md（仕様）

## 進捗（Plan 開始時に必ず確認）

docs/desktop_refactoring_roadmap_plan_prompt.md の「現在地」「進捗チェックリスト」を読み、
完了済み Phase をやり直さない。未指定なら **チェックリストで最初の未完了 Phase** から開始する
（現時点の必須トラックは完了。残りは任意の Track A Phase 3 等）。

## 現状の問題（優先度順）

1. **巨大 UI / サービスファイル**
   - python/desktop/ui/image_manager_widget.py … **シム化済**（本体は `ui/image_manager/`）
   - python/desktop/ui/receipt_widget.py … **シム化済**（本体は `ui/receipt/`）
   - python/desktop/ui/inventory_widget.py … **シム化済**（本体は `ui/inventory/`）
   - python/desktop/ui/product_widget.py … **シム化済**（本体は `ui/product/`）
   - python/desktop/services/keepa_service.py … **シム化済**（本体は `services/keepa/`）
   - python/desktop/ui/route_summary_widget.py … **シム化済**（本体は `ui/route_summary/`）
   - python/desktop/ui/store_master_widget.py … **シム化済**（本体は `ui/store_master/`）

2. **import フォールバック乱立**（一部解消済み）
   - product_widget: Track A Phase 1 で compat 集約済み
   - database/*.py の db_paths: Track X Phase 0 で `db_path_resolve` に集約済み
   - settings_widget.py: Track X Phase 1 で compat 集約済み
   - 起動時 sys.path（**Track X Phase 2 完了**・分割パッケージ内は残置）

3. **テスト不足**
   - Track A/B/C/D/E（Keepa・route_summary・store_master）の純関数安全網は追加済み（desktop/tests **164件**）
   - image_manager / keepa / route_summary / store_master の分割は完了

4. **サービス層の肥大**
   - keepa_service.py（約 1,100 行）、image_service.py、receipt_service.py 等

## 絶対ルール（必ず守る）

- **挙動は変えない** — ファイル移動・整理・テスト追加のみ。ロジック変更は別タスク
- **1 Phase ずつ** — まとめて全部やらない。1 Plan = 1 Phase
- **各ステップ後に pytest を実行** — 失敗したら次に進まない
- **コミットは Phase 単位** — ユーザーが明示的に依頼したときのみ
- **対象外を触らない** — 指定トラック以外の巨大ファイル・無関係機能は変更しない
- **価格改定コアは触らない** — python/services/repricer_*.py、ui/repricer/ のロジック変更禁止（compat 利用拡大のみ許可）
- **手動確認を重視** — UI 分割後は該当タブの主要操作をユーザーが確認するまで次 Phase に進まない
- **進捗を更新** — Phase 完了後に本道筋のチェックリストと cursor_development_progress.md を更新する

## おすすめトラック順

Track A（仕入DB）→ Track B（在庫）→ Track X（横断 import、A/B の合間でも可）
→ Track C（レシート）→ Track D（画像管理）→ Track E（その他）

未指定時はチェックリスト上の **最初の未完了**（現時点では任意の Track A Phase 3 等）から開始する。

---

### Track A: 仕入DB（product_widget）【最優先】

#### Track A Phase 0: 安全網（テスト追加）【完了】

**目的**: 分割前後で仕入DBまわりの挙動が同じであることを機械的に検証できるようにする。

**完了内容**: desktop/tests に purchase_cost_calc / channel_cost / break_even / inventory_only / elapsed_days / repricing_summary を追加。既存テストの import を desktop.* に統一。

**検証**:
```bash
cd python
python -m pytest desktop/tests/ -v --ignore=desktop/scripts/
```

---

#### Track A Phase 1: product_widget の import 整理【完了】

**目的**: product_widget 内の try/except ImportError を `_desktop_import_compat` 等に寄せる。

**完了内容**: `_desktop_import_compat.py` 拡張、product_widget は先頭1ブロックのみ。UI は `_desktop_ui_compat`。

---

#### Track A Phase 2: product_widget のモジュール分割【完了】

**前提**: Track A Phase 0・1 完了。

**完了内容**:
- `ui/product/` パッケージ（`widget.py` / `support.py` / `purchase_*_mixin.py`）
- `product_widget.py` 後方互換シム
- コピペ移動のみ（ロジック変更なし）。販売タブは widget.py に残置
- 検索 NameError 修正済（`PurchaseTableMixin._receipt_image_lookup_key`）
- 検証: ProductWidget import OK。手動確認 OK

---

#### Track A Phase 3（任意）: purchase_row_edit_dialog 分割【完了】

**前提**: Track A Phase 2 完了・手動確認 OK。

**完了内容**:
- `ui/purchase_row_edit/` パッケージ:
  - `support.py` … 定数・純関数・Win32 ヘルパ
  - `tp_mixin.py` … TP 入力・利益率・帯ハイライト
  - `ladder_mixin.py` … 月別ラダー UI 連携
  - `fee_channel_mixin.py` … チャネル・手数料・SKU日付
  - `dialog.py` … オーケストレーター（`_setup_ui` / `_apply` / Keepa 等）
  - `__init__.py`
- `purchase_row_edit_dialog.py` 後方互換シム
- バックアップ: `purchase_row_edit_dialog.py.bak_phase3`
- コピペ移動のみ。見た目・操作フロー・utils（`repricer_ladder_table` 等）は未変更
- `_desktop_ui_compat` 経由の import は変更不要
- 検証: PurchaseRowEditDialog import OK、desktop/tests **167件**パス
- **手動確認 OK**: 仕入DB → 行編集（TP・月別・手数料・保存）

---

### Track B: 在庫（inventory_widget）

#### Track B Phase 0: 安全網【完了】

**完了内容**:
- `test_inventory_store_matching.py` … `attach_route_date_to_store_visits` / `RouteMatchingService`
- `test_condition_labels.py` … コンディション番号↔ラベル
- `test_inventory_jan_normalize.py` … JAN `.0` 除去
- `test_csv_io_validate.py` … CSV 構造検証・正規化
- `test_purchase_inventory_only.py` … SKU正規化・ステータス・upsert payload を拡充
- `inventory_widget.py` は未変更
- 検証: desktop/tests **96件**パス

---

#### Track B Phase 1: inventory_widget 分割【完了・手動確認待ち】

**前提**: Track B Phase 0、Track A 完了。

**完了内容**:
- `ui/inventory/` パッケージ（widget / support / dialogs / mixins）
- `inventory_widget.py` 後方互換シム（`dev_mode` も同一クラス）
- コピペ移動のみ。照合・プライスター方式は未変更
- バックアップ: `inventory_widget.py.bak_phase1`
- 検証: InventoryWidget import OK、desktop/tests 96件パス

**残作業**: なし（在庫タブ手動確認 OK）

---

### Track X: 横断（import / DB bootstrap）【①②の合間でも可】

#### Track X Phase 0: DB 層 bootstrap 統一【完了】

**前提**: Track B Phase 1 完了・在庫タブ手動確認 OK。

**完了内容**:
- `database/db_path_resolve.py` に `resolve_hirio_db_path` / `resolve_product_purchase_db_path` / `resolve_inventory_route_db_path` を集約
- database 18ファイルが相対 import で利用（try/except 重複を削除）
- `db_paths.py` / `db_bootstrap.py` 本体ロジックは未変更
- 検証: desktop/tests **96件**パス

---

#### Track X Phase 1: settings_widget の import 整理【完了】

**前提**: Track X Phase 0 完了。

**完了内容**:
- `_desktop_import_compat` に backup / recording / OCR / settings_helper / api_test / gemini / StoreDatabase を追加
- `_desktop_ui_compat` に `FleaMarketSettingsWidget` を追加
- `settings_widget.py` 先頭1ブロックに集約（設定項目・デフォルト値は未変更）
- 検証: SettingsWidget import OK、desktop/tests **96件**パス

---

#### Track X Phase 2（任意・慎重）: 起動時 sys.path の整理【完了】

**目的**: `main.py` と各 widget の `sys.path.insert` 乱立を減らし、import を1系統に近づける。

**完了内容**:
- `utils/ensure_desktop_sys_path.py` … `ensure_desktop_on_sys_path()`（**desktop 先頭 + python/ 次点**）/ `get_desktop_root()` / `get_python_root()`
- `main.py` 起動直後に呼び出し
- 平坦 UI 約 19 ファイルの重複 insert をヘルパーへ置換（`company_master` / `barcode_checker` / `route_list` の誤った `../..` も desktop に修正）。ヘルパー import は `desktop.utils` フォールバック付き
- `ocr_service.py` / `settings_widget` OCR テスト箇所をヘルパー化（pytest 用 `desktop.utils` フォールバック付き）
- `test_ensure_desktop_sys_path.py`（3件）— path 順序・`database` / `desktop.utils` import
- **フォロー**: 起動時 `No module named 'desktop'` を python/ 追加で解消
- **未変更**: 分割済みパッケージ内 `_desktop_root`、GCS 動的 path、`journal_entry_widget` の独自挿入、scripts
- 検証: desktop/tests **167件**パス（旧164 + 3）
- **手動確認 OK**: アプリ起動・主要タブが開けることを確認

---

### Track C: レシート（receipt_widget）【巨大・慎重】

#### Track C Phase 0: 安全網【完了】

**完了内容**:
- `test_receipt_sku_linking.py` 拡充（正規化・日時・画像優先マッチ）
- `test_receipt_purchase_price_policy.py` / `test_receipt_matching_normalize.py` / `test_receipt_parse_text.py` 新規
- `receipt_widget.py` は未変更
- 検証: desktop/tests **118件**パス

#### Track C Phase 1: receipt_widget 分割【完了】

**前提**: Track C Phase 0 完了。

**完了内容**:
- `ui/receipt/` パッケージ（widget / support / dialogs・Thread / mixins×9）
- `receipt_widget.py` 後方互換シム
- コピペ移動のみ。OCR・保存形式は未変更
- バックアップ: `receipt_widget.py.bak_phase1`
- フォロー修正: `receipt_processed` Signal、GCS/`__file__` 階層・スナップショットパス
- 検証: ReceiptWidget import OK、desktop/tests 118件パス
- 証憑タブ手動確認 OK（全件OCR・GCSアップロード含む）

---

### Track D: 画像管理（image_manager_widget）

#### Track D Phase 0: 安全網【完了】

**完了内容**:
- `test_amazon_image_naming.py` 拡充（11→18件）
- `test_image_service.py` 新規（JAN抽出・group_by_jan・プリセット・保存形式・自動補正）
- ウィジェット先頭ヘルパー直接テストは見送り（`python/utils` vs `desktop/utils` 衝突）
- `image_manager_widget.py` 未変更
- 検証: desktop/tests **134件**パス

#### Track D Phase 1: image_manager_widget 分割【完了・手動確認は後回し可】

**前提**: Track D Phase 0 完了。

**完了内容**:
- `ui/image_manager/` パッケージ（widget / support / workflow・scan・tree・preview・rename・purchase_link・registration・gcs・amazon_template mixin）
- `image_manager_widget.py` 後方互換シム
- コピペ移動のみ。リネーム規則・ZIP 方針は未変更
- バックアップ: `image_manager_widget.py.bak_phase1`
- Signal / `__file__` 階層 / `@staticmethod` を維持
- 検証: ImageManagerWidget import OK、desktop/tests **134件**パス（当時）

**残作業**: 画像管理タブ手動確認は**後回し可**（テスト画像がない場合）。エラーが出たらそのとき修正。

---

### Track E: Keepa / その他

#### Track E Phase 0: Keepa 安全網【完了】

**完了内容**:
- `test_keepa_service.py` 新規（10件）— 価格/ランク抽出、offerCSV、円スケール、369集計ヘルパー、コンディションラベル
- Keepa 実 API・UI・`keepa_service.py` 本体は未変更
- 検証: desktop/tests **144件**パス

#### Track E Phase 1: keepa_service モジュール分割【完了】

**前提**: Track E Phase 0 完了（`test_keepa_service.py` グリーン）。

**完了内容**:
- `services/keepa/` パッケージ（models / price_helpers / offer_helpers / analysis_369 / service + `__init__`）
- Mixin 方式: `KeepaService(KeepaPriceHelpersMixin, KeepaOfferHelpersMixin, Keepa369AnalysisMixin)`
- `keepa_service.py` 後方互換シム（`KeepaService` / dataclass 再エクスポート）
- バックアップ: `keepa_service.py.bak_phase1`
- 自己参照修正: `KeepaOfferHelpersMixin._offer_csv_numbers`（分割後 NameError 防止）
- API・Gemini プロンプト・リトライは未変更
- 検証: KeepaService / KeepaProductInfo / KeepaOfferRow import OK、desktop/tests **144件**パス

#### Track E route_summary Phase 0: 安全網【完了】

**完了内容**:
- `test_route_summary_helpers.py`（4件）— `_template_include_from_db_value` / notes マージ / store_code
- `test_route_template_time_validation.py`（4件）— 出発・帰宅・店舗 IN/OUT 整合
- `test_route_visit_normalize.py`（3件）— IN 時刻順・滞在/移動・フォルダ名パース
- `_source_symbol_loader.py` … `python/utils` vs `desktop/utils` 衝突回避のため AST 抽出（ウィジェット本体は未 import）
- `route_summary_widget.py` / サービス本体は未変更
- 検証: desktop/tests **155件**パス（旧144 + 11）

#### Track E route_summary Phase 1: route_summary_widget 分割【完了】

**前提**: route_summary Phase 0 完了。

**完了内容**:
- `ui/route_summary/`（widget / support / workflow・map・visit_table・template・matching・persistence・calc mixin）
- `route_summary_widget.py` 後方互換シム
- バックアップ: `route_summary_widget.py.bak_phase1`
- `sys.path` を `../..`（desktop）に補正、`data_saved` Signal 維持
- 自己参照: `RouteSummaryVisitTableMixin._merge_notes_for_template_export`
- Phase 0 テストのソースパスを support / visit_table_mixin へ更新
- 検証: RouteSummaryWidget import OK（`data_saved` 含む）、desktop/tests **155件**パス

**残作業**: ルート選択タブ手動確認は後回し可（エラー時に修正）

#### Track E store_master Phase 0: 店舗マスタ安全網【完了】

**前提**: route_summary Phase 0〜1 完了。desktop/tests **155件**グリーンだった。

**完了内容**:
- `test_store_master_helpers.py`（9件）— `_coerce_coordinate` / `_store_has_coordinates`（`StoreListWidget`）/ `_suggest_platform_tokens` / `_suggest_tokens` / `_normalize_entries`
- `_source_symbol_loader` で AST 抽出（UI 生成なし）
- `store_master_widget.py` / DB スキーマは未変更
- 既存 `test_route_code_ensure.py` は触らず再実行のみ
- 検証: desktop/tests **164件**パス（旧155 + 9）

#### Track E store_master Phase 1: store_master_widget 分割【完了】

**前提**: store_master Phase 0 完了（`test_store_master_helpers.py` グリーン）。desktop/tests **164件**。

**完了内容**:
- `ui/store_master/` パッケージ（ドメイン別）:
  - `widget.py` … `StoreMasterWidget`（タブ容器）
  - `support.py` … Google Maps import フォールバック
  - `store_dialogs.py` … `StoreEditDialog` / `CustomFieldEditDialog`
  - `route_dialogs.py` … `DraggableStoreListWidget` / `RouteManagementDialog`
  - `store_list.py` … `StoreListWidget`
  - `expense.py` / `online.py` / `flea_users.py`
  - `__init__.py` … 公開クラス再エクスポート
- `store_master_widget.py` 後方互換シム（外部利用クラスも再エクスポート）
- バックアップ: `store_master_widget.py.bak_phase1`
- `sys.path`=`../..`、`@staticmethod` 維持、コピペ移動のみ
- Phase 0 テストのソースパスを分割先へ更新
- 検証: StoreMasterWidget / OnlinePlatformListWidget / CustomFieldEditDialog / FleaMarketUserEditDialog import OK、desktop/tests **164件**パス

**残作業**: 店舗マスタタブ手動確認は後回し可（エラー時に修正）

**その他（余力・別 Phase）**:
- purchase_inventory_only の import 整理・分割
- Track X Phase 2 / Track A Phase 3（任意）

---

### 価格改定の仕上げ（任意・別タスク）

価格改定コアは完了済み。必要なら別 Plan で:

- `repricer/result_mixin.py` のさらなる分割
- `repricer_settings_widget.py` の分割
- DEBUG print 削除（挙動確認付き）

詳細は `docs/repricer_refactoring_plan_prompt.md` を参照。

---

## テスト実行コマンド（共通）

```bash
cd python

# デスクトップテスト
python -m pytest desktop/tests/ -v --ignore=desktop/scripts/

# 価格改定（回帰確認・触っていなくても時々実行推奨）
python -m pytest tests/test_repricer_weekly.py tests/test_repricer_utils_sync.py -v

# まとめて
python -m pytest desktop/tests/ tests/ -v --ignore=desktop/scripts/
```

## 主要ファイル一覧（道筋対象）

| ファイル | 役割 | トラック |
|----------|------|----------|
| python/desktop/ui/product_widget.py | 仕入DB UI シム | A Phase 2 **完了** |
| python/desktop/ui/product/ | 仕入DB UI 本体 | A Phase 2 **完了** |
| python/desktop/ui/inventory_widget.py | 在庫 UI シム | B Phase 1 **完了** |
| python/desktop/ui/inventory/ | 在庫 UI 本体 | B Phase 1 **完了** |
| python/desktop/utils/ensure_desktop_sys_path.py | desktop の sys.path 冪等追加 | **X Phase 2 完了** |
| python/desktop/utils/_desktop_import_compat.py | import 互換 | A/X（拡張済） |
| python/desktop/ui/purchase_row_edit_dialog.py | 仕入行編集シム | **A Phase 3 完了** |
| python/desktop/ui/purchase_row_edit/ | 仕入行編集本体 | **A Phase 3 完了** |
| python/desktop/database/db_path_resolve.py | DB パス解決 | **X Phase 0 完了** |
| python/desktop/utils/db_paths.py | DB パス本体 | X Phase 0（参照のみ・未変更） |
| python/desktop/ui/settings_widget.py | 設定 | **X Phase 1 完了** |
| python/desktop/ui/receipt_widget.py | レシート UI シム | **C Phase 1 完了** |
| python/desktop/ui/receipt/ | レシート UI 本体 | **C Phase 1 完了** |
| python/desktop/ui/image_manager_widget.py | 画像管理 UI シム | **D Phase 1 完了**（手動確認は後回し可） |
| python/desktop/ui/image_manager/ | 画像管理 UI 本体 | **D Phase 1 完了** |
| python/desktop/services/keepa_service.py | Keepa シム | **E Phase 1 完了** |
| python/desktop/services/keepa/ | Keepa 本体 | **E Phase 1 完了** |
| python/desktop/ui/route_summary_widget.py | ルート集計シム | **E route_summary Phase 1 完了** |
| python/desktop/ui/route_summary/ | ルート集計本体 | **E route_summary Phase 1 完了** |
| python/desktop/ui/store_master_widget.py | 店舗マスタ UI シム | **E store_master Phase 1 完了** |
| python/desktop/ui/store_master/ | 店舗マスタ UI 本体 | **E store_master Phase 1 完了** |

## Plan 作成時のお願い

- まず **どの Track / Phase から始めるか** を確認する（未指定ならチェックリストの最初の未完了）
- 各ステップに **検証方法**（pytest・手動確認項目）を含める
- **変更ファイル一覧** と **変更しないファイル** を明示する
- UI 分割 Phase では **移動先マッピング表** を実装前に出す
- 不明点があれば実装前に質問する（推測でロジックを変えない）
- 完了後は `docs/cursor_development_progress.md` と本ファイルのチェックリスト／現在地を更新する
```

---

## Phase 別の追記例

Plan モードでこの MD を @ したあと、先頭に次のいずれかを追加する。

### Track A Phase 3 のみ（完了済み・再実行不要）

```
Track A Phase 3 から開始してください。
```

### Track X Phase 2 のみ（完了済み・再実行不要）

```
Track X Phase 2 から開始してください。
```

### Track E store_master Phase 1 のみ（完了済み・再実行不要）

```
Track E store_master Phase 1 から開始してください。
```

### Track E store_master Phase 0 のみ（完了済み・再実行不要）

```
Track E store_master Phase 0 から開始してください。
```

### Track E route_summary Phase 1 のみ（完了済み・再実行不要）

```
Track E route_summary Phase 1 から開始してください。
```

### Track E route_summary Phase 0 のみ（完了済み・再実行不要）

```
Track E route_summary Phase 0 から開始してください。
```

### Track E Phase 1（Keepa 分割）のみ（完了済み・再実行不要）

```
Track E Phase 1 から開始してください。
```

### Track E Phase 0（Keepa 安全網）のみ（完了済み・再実行不要）

```
Track E Phase 0 から開始してください。
```

### Track D Phase 1 のみ（完了済み・手動確認は後回し可）

```
Track D Phase 1 から開始してください。
```

### Track D Phase 0 のみ（完了済み・再実行不要）

```
Track D Phase 0 から開始してください。
```

### Track C Phase 1 のみ（完了済み・再実行不要）

```
Track C Phase 1 から開始してください。
```

### Track C Phase 0 のみ（完了済み・再実行不要）

```
Track C Phase 0 から開始してください。
```

### Track X Phase 1 のみ（完了済み・再実行不要）

```
Track X Phase 1 から開始してください。
```

### Track X Phase 0 のみ（完了済み・再実行不要）

```
Track X Phase 0 から開始してください。
```

### Track B Phase 1 のみ（完了済み・再実行不要）

```
Track B Phase 1 から開始してください。
```

### Track B Phase 0 のみ（完了済み・再実行不要）

```
Track B Phase 0 から開始してください。
```

### Track A Phase 2 のみ（完了済み・再実行不要）

```
Track A Phase 2 から開始してください。
```

### Track A Phase 3 のみ（任意）

```
Track A Phase 3 から開始してください。Track A Phase 0〜2 は完了済み・手動確認 OK です。
```

---

## 進捗チェックリスト（ユーザー用）

- [x] 価格改定 Phase 0〜6
- [x] Track A Phase 0（仕入DB テスト）
- [x] Track A Phase 1（product_widget import）
- [x] Track A Phase 2（product_widget 分割・手動確認 OK）
- [x] Track A Phase 3（行編集ダイアログ分割・167件・手動確認 OK）
- [x] Track B Phase 0（在庫 安全網）
- [x] Track B Phase 1（inventory_widget 分割・手動確認 OK）
- [x] Track X Phase 0（DB bootstrap / db_path_resolve）
- [x] Track X Phase 1（settings_widget import）
- [x] Track X Phase 2（sys.path・167件・手動確認 OK）
- [x] Track C Phase 0（レシート安全網）
- [x] Track C Phase 1（receipt_widget 分割・手動確認 OK）
- [x] Track D Phase 0（画像管理安全網）
- [x] Track D Phase 1（image_manager 分割・手動確認は後回し可）
- [x] Track E Phase 0（Keepa 安全網・144件）
- [x] Track E Phase 1（keepa_service 分割・144件）
- [x] Track E route_summary Phase 0（安全網・155件）
- [x] Track E route_summary Phase 1（route_summary 分割・155件・手動確認は後回し可）
- [x] Track E store_master Phase 0（店舗マスタ安全網・164件）
- [x] Track E store_master Phase 1（`ui/store_master/` 分割・164件・手動確認は後回し可）

---

## 参考: 価格改定で得たパターン（再利用）

次の画面でも同じ型で進める。

1. **Phase 0**: スナップショット or 純関数テスト
2. **Phase 1**: import / 重複の整理（compat レイヤー）
3. **Phase 2**: `ui/<feature>/` パッケージ + mixin + 後方互換シム
4. **手動確認** してから次トラックへ
5. 進捗は `docs/cursor_development_progress.md` と本ファイルを更新

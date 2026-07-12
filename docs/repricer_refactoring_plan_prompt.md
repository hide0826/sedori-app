# 価格改定リファクタリング — Plan モード用プロンプト

物理バックアップ済み。Cursor の **Plan モード** に貼り付けて使うための指示書です。

## 使い方

1. Cursor で **Plan モード** に切り替える
2. 下の「## Plan モードに貼り付けるプロンプト」ブロックを **そのままコピー** して貼り付ける
3. **Phase 番号だけ** 先頭に追記して実行する（例: `Phase 0 から開始してください`）
4. 1 Phase 完了・確認後、次の Phase 用に再度 Plan を投げる（**1 Plan = 1 Phase**）

---

## Plan モードに貼り付けるプロンプト

```
# タスク: HIRIO 価格改定モジュールの慎重なリファクタリング

## 背景

中古せどり業務自動化システム「HIRIO」の価格改定機能をリファクタリングする。
物理バックアップは取得済み。本番運用中のため、**挙動を変えずに**コード整理のみ行う。

関連ドキュメント:
- docs/reprice_rules_guide.md（改定ルール仕様）
- config/reprice_rules.json（設定ファイル）

## 現状の問題

1. **重複コピー**: 以下のファイルが API 用とデスクトップ用で二重管理され、ハッシュが一致しない（手動同期でズレるリスク）
   - python/utils/repricer_tp_target.py
   - python/desktop/utils/repricer_tp_target.py
   - python/utils/repricer_ladder_core.py
   - python/desktop/utils/repricer_ladder_core.py

2. **巨大ファイル**:
   - python/services/repricer_weekly.py（約1,300行）— 標準改定・3-6-9・仕入DB連携が混在
   - python/desktop/ui/repricer_widget.py（約2,400行・メソッド75個）— UI と業務ロジック混在

3. **テスト不足**: 価格改定ロジック用の自動テストがほぼない
   - サンプル CSV のみ: pwa/test_repricer.csv

4. **import フォールバック乱立**: 複数ファイルで try/except による desktop/utils ↔ utils の切り替えがある
   - python/desktop/ui/repricer_settings_widget.py
   - python/desktop/services/repricer_369_presets.py
   - python/desktop/ui/purchase_row_edit_dialog.py
   - python/desktop/services/purchase_ladder_autofill_batch.py

## 絶対ルール（必ず守る）

- **挙動は変えない** — ファイル移動・整理・テスト追加のみ。ロジック変更は別タスク
- **1 Phase ずつ** — まとめて全部やらない
- **各ステップ後に pytest を実行** — 失敗したら次に進まない
- **コミットは Phase 単位** — ユーザーが明示的に依頼したときのみ
- **対象外を触らない** — 価格改定と無関係なファイル（store_db, カスタマー対応AI 等）は変更しない
- **FastAPI とデスクトップの両方** で同じ改定結果になることを確認する

## フェーズ計画

### Phase 0: 安全網（スナップショットテスト追加）【最優先・リスク低】

**目的**: リファクタ前後で改定結果が同じであることを機械的に検証できるようにする。

**やること**:
1. python/tests/test_repricer_weekly.py を新規作成
2. pwa/test_repricer.csv をフィクスチャとして使用
3. apply_repricing_rules() の出力（updated_rows, items の sku/price/new_price/action 等）をスナップショット比較
4. standard モードと 369 モードの両方を最低1ケースずつテスト
5. repricer_tp_target / repricer_ladder_core の単体テストも追加（現行コピー2箇所の出力が一致することを検証）

**やらないこと**:
- 既存ロジックの変更
- UI の変更

**完了条件**:
- pytest がグリーン
- テストが repricer_weekly の主要パスをカバーしている

---

### Phase 1: 重複ユーティリティ統合【リスク中】

**前提**: Phase 0 のテストがすべてパスしていること。

**目的**: repricer_tp_target / repricer_ladder_core の二重管理を解消し、単一の正（canonical）にする。

**やること**:
1. 正とするファイルを python/utils/ 側に統一（内容は両コピーの差分をマージして最新に）
2. python/desktop/utils/ のコピーを削除、または canonical への re-export シムに置き換え
3. try/except import フォールバックを整理し、import パスを1系統に
4. 影響ファイルを順に修正:
   - python/services/repricer_weekly.py
   - python/desktop/ui/repricer_settings_widget.py
   - python/desktop/services/repricer_369_presets.py
   - python/desktop/utils/repricer_ladder_table.py
   - python/desktop/utils/purchase_repricing_summary.py
5. Phase 0 のテストを再実行して結果不変を確認

**やらないこと**:
- repricer_weekly.py の分割（Phase 2）
- repricer_widget.py の触り（Phase 3）

**完了条件**:
- repricer_tp_target / repricer_ladder_core が実質1か所のみ
- pytest グリーン
- スナップショットテストの出力が Phase 0 と同一

---

### Phase 2: repricer_weekly.py のモジュール分割【リスク中〜高】

**前提**: Phase 0 + Phase 1 完了。

**目的**: 約1,300行の repricer_weekly.py を責務ごとに分割し、可読性を上げる。

**分割案**（名前は実装時に調整可）:
- python/services/repricer_standard.py — 標準改定ロジック
- python/services/repricer_369.py — 3-6-9 改定ロジック
- python/services/repricer_purchase_db.py — 仕入DB（TP・ラダー・改定OFF）読み込み
- python/services/repricer_weekly.py — 公開 API のみ（apply_repricing_rules, preprocess_dataframe 等を re-export）

**やること**:
1. 上記案で Plan を具体化（関数の移動先マッピング表を先に作る）
2. 関数を移動（中身はコピペ、ロジック変更なし）
3. import を更新（python/routers/repricer.py, デスクトップ側の参照も確認）
4. Phase 0 テストで結果不変を確認

**やらないこと**:
- アルゴリズムの改善・最適化
- DEBUG print の削除（挙動に影響しうるため別タスク）

**完了条件**:
- repricer_weekly.py が薄いファサードになる
- pytest グリーン・スナップショット不変

---

### Phase 3: repricer_widget.py の UI 分割【リスク高・任意】

**前提**: Phase 0〜2 完了。手動での画面操作確認も実施済み。

**目的**: 約2,400行の RepricerWidget をサブコンポーネントに分割。

**分割案**:
- CSV 取込・前処理パネル
- プレビュー結果テーブル
- プライスター連携パネル（ブラウザ＋ドラッグ運用）
- ワークフロー進捗表示

**やらないこと**:
- 画面レイアウト・UX の変更
- プライスター連携方式の変更（手動ドラッグ運用を維持）

**完了条件**:
- RepricerWidget がオーケストレーター程度のサイズになる
- デスクトップアプリで価格改定タブの手動確認が問題なし

---

### Phase 4: repricer パッケージの import 整理【リスク低】

**前提**: Phase 0〜3 完了。31 pytest グリーン。

**目的**: Phase 3 で分割した `ui/repricer/` 各 mixin にコピペされた try/except import を1か所に集約し、未使用 import を削除する。

**やること**:
1. `support.py` に共通 compat import を集約（DraggableFileIcon / browser_front_scheduler / KeepaService / validate_csv_file 等）
2. 各 mixin から重複ブロックを削除し `support` から import
3. `workflow_mixin.py` / `preview_mixin.py` の未使用 import を整理
4. Phase 0 テスト + `from ui.repricer.widget import RepricerWidget` の import 確認

**やらないこと**:
- purchase_row_edit_dialog / purchase_ladder_autofill_batch のフォールバック整理（Phase 5 候補）
- ロジック・UI レイアウトの変更

**完了条件**:
- pytest グリーン
- デスクトップから RepricerWidget が import 可能

---

### Phase 5: 仕入DB連携ファイルの import 整理【リスク低】

**前提**: Phase 0〜4 完了。手動確認 OK。

**目的**: Phase 1 で残っていた仕入DB×改定まわりの try/except import フォールバックを1か所に集約する。

**やること**:
1. `desktop/utils/_purchase_repricer_imports.py` を新設（elapsed_days / repricer_ladder_table / settings_helper の互換レイヤー）
2. 以下を compat 経由に変更:
   - `purchase_repricing_summary.py`（相対 import）
   - `purchase_ladder_autofill_batch.py`
   - `purchase_row_edit_dialog.py`（改定関連 utils のみ）
3. Phase 0 テスト + desktop / python 両方からの import 確認

**やらないこと**:
- purchase_row_edit_dialog 内の services / database フォールバック（別タスク）
- product_widget 内の lazy import フォールバック

**完了条件**:
- pytest グリーン
- `utils.*` / `desktop.utils.*` 両パスから import 可能

---

### Phase 6: 仕入DBダイアログ・product_widget の import 整理【リスク低】

**前提**: Phase 0〜5 完了。

**目的**: `purchase_row_edit_dialog` の services フォールバックと、改定連携の lazy import を compat レイヤーに集約する。

**やること**:
1. `desktop/utils/_desktop_import_compat.py` … services / database / summarize（循環回避のため UI は含めない）
2. `desktop/utils/_desktop_ui_compat.py` … `PurchaseRowEditDialog` のみ（循環 import 防止用に分離）
3. `purchase_row_edit_dialog.py` … compat 経由に統合
4. `product_widget.py` / `repricer/result_mixin.py` … 改定連携 lazy import を compat 経由に
5. pytest + 両パス import 確認

**やらないこと**:
- `product_widget.py` 全体の import 整理（フリマ・手数料等のモジュールレベルフォールバック）
- `result_mixin.py` の inventory_only 等の lazy import

**完了条件**:
- pytest グリーン
- 循環 import なしで `PurchaseRowEditDialog` / `RepricerWidget` が import 可能

---

## テスト実行コマンド

```bash
# リポジトリルートから
cd python
python -m pytest tests/test_repricer_weekly.py -v

# デスクトップ関連テストも含めて確認する場合
python -m pytest desktop/tests/ tests/ -v --ignore=desktop/scripts/
```

## 主要ファイル一覧

| ファイル | 役割 |
|----------|------|
| python/services/repricer_weekly.py | 改定計算の中核 |
| python/routers/repricer.py | FastAPI エンドポイント |
| python/desktop/ui/repricer_widget.py | デスクトップ UI |
| python/desktop/ui/repricer_settings_widget.py | 改定ルール設定 UI |
| python/desktop/services/repricer_369_presets.py | 3-6-9 簡単プリセット |
| python/utils/repricer_tp_target.py | TP 解釈ロジック（API 正） |
| python/utils/repricer_ladder_core.py | 月別ラダー共通ロジック（API 正） |
| config/reprice_rules.json | 改定ルール設定 |
| pwa/test_repricer.csv | テスト用サンプル CSV |

## Plan 作成時のお願い

- まず **どの Phase から始めるか** を確認する（未指定なら Phase 0）
- 各ステップに **検証方法**（pytest コマンド・確認項目）を含める
- 変更ファイル一覧と **変更しないファイル** を明示する
- 不明点があれば実装前に質問する（推測でロジックを変えない）
```

---

## Phase 別の追記例

Plan に貼り付けたあと、先頭または末尾に次のいずれかを追加する。

### Phase 0 のみ

```
Phase 0 から開始してください。Phase 0 完了後は止まり、結果を報告してください。
```

### Phase 1 のみ

```
Phase 1 から開始してください。Phase 0 のテスト（python/tests/test_repricer_weekly.py）は既に存在する前提です。
```

### Phase 2 のみ

```
Phase 2 から開始してください。Phase 0・1 は完了済みです。まず関数の移動先マッピング表を Plan に含めてから実装してください。
```

### Phase 4 のみ

```
Phase 4 から開始してください。Phase 0〜3 は完了済みです。
```

### Phase 5 のみ

```
Phase 5 から開始してください。Phase 0〜4 は完了済みです。
```

### Phase 6 のみ

```
Phase 6 から開始してください。Phase 0〜5 は完了済みです。
```

---

## 参考: 重複ファイルの現状

デスクトップ側コピーには「API 側と同期すること」というコメントがあるが、実際にはハッシュが一致していない。

| ファイル | API 側 | デスクトップ側 |
|----------|--------|----------------|
| repricer_tp_target.py | python/utils/ | python/desktop/utils/ |
| repricer_ladder_core.py | python/utils/ | python/desktop/utils/ |

import パスの都合で desktop 実行時に `utils.*` が `python/desktop/utils` を指すことがあり、フォールバック import が散在している。Phase 1 でこれを解消する。

# HIRIO 3-6-9価格改定 実装ハンドオーバー（次チャット用）

## 目的

`3-6-9価格改定` タブで、SKUタグ（3/6/9）に応じて別ルールを適用し、  
Keepa同コンディション最安値（直近）を使って「ざっくり引き直し」で価格改定する。

同時に、`keepa_min < TP下限` のASINを **理由欄アラート** で可視化する。

---

## この実装で確定している要件（ユーザー合意）

1. **アラート表示場所**  
   - 価格改定結果の `理由` 列で表示する（専用列は作らない）。

2. **3-6-9別ルール**  
   - `改定ルール` を `3 / 6 / 9` のサブタブに分離する。
   - それぞれに TP利益保持率を設定可能にする。
   - 例:  
     - 3ルール: TP0=95%, TP1=75%, TP2=60%  
     - 6ルール: TP0=90%, TP1=70%, TP2=55%

3. **SKUタグでルール選択**  
   - 仕入時にSKUへ入れている 3/6/9タグを判定して、3用/6用/9用ルールを適用する。

4. **Keepa最安の扱い**  
   - 「同コンディションの最安（min）」は **直近** で良い。
   - 毎回観測時に、そこからスケジュールをざっくり引き直す。

5. **下限割れ時の挙動**  
   - `keepa_min < TP下限` の場合は **価格をTP下限で固定**（下げない）。
   - そのSKUはアラート表示する。
   - 必要ならユーザーが目視で手動調整する運用。

6. **厳密等間隔は不要**  
   - 「ざっくり引き直し」でOK。売り切り優先（利益バランス重視）。

---

## 現状コードの前提（重要）

- `python/services/repricer_weekly.py` は現在、固定アクション（`price_down_1` 等）中心で、  
  Keepa最安値を直接使うロジックはない。
- `akaji` はアプリ内部の計算下限としてはほぼ使っていないが、  
  **Prister側でストッパーとして効く運用** を前提にする。
- `price_down_ignore` のときだけ `akaji` を空にする既存仕様があるため、  
  今回機能では `akaji` を生かす運用を前提に注意する。
- 既に `3-6-9価格改定` タブ（`main_window.py`）は複製済み。

---

## 実装方針（推奨）

## 1) 設定構造を「3/6/9プロファイル」に拡張

対象:
- `config/reprice_rules.json`
- `python/routers/repricer.py`（Pydanticモデル）
- `python/services/repricer_weekly.py`（load_config）
- `python/desktop/ui/repricer_settings_widget.py`（保存/読込UI）

追加する設定（例）:

```json
{
  "rule_profiles": {
    "3": { "tp_rates": { "tp0": 95, "tp1": 75, "tp2": 60, "tp3": 0 } },
    "6": { "tp_rates": { "tp0": 90, "tp1": 70, "tp2": 55, "tp3": 0 } },
    "9": { "tp_rates": { "tp0": 85, "tp1": 65, "tp2": 50, "tp3": 0 } }
  },
  "default_profile": "6",
  "interval_days": 7,
  "alerts": {
    "enabled": true,
    "reason_prefix": "ALERT"
  }
}
```

注意:
- 既存 `reprice_rules` は後方互換維持（既存タブへの影響を避ける）。
- 3-6-9用は別キーで管理。

---

## 2) 改定ルールUIを 3/6/9 サブタブ化

対象:
- `python/desktop/ui/repricer_settings_widget.py`

要件:
- `QTabWidget` を追加して `3ヶ月 / 6ヶ月 / 9ヶ月` サブタブを作る。
- 各タブに以下入力:
  - TP0利益保持率(%)
  - TP1利益保持率(%)
  - TP2利益保持率(%)
  - （将来用にTP3欄を持っても良い）
- 共通設定として:
  - `interval_days`（例: 7日）
  - デフォルトプロファイル
  - アラート有効/無効（初期は有効）

表示ラベルは初心者向けに分かりやすく:
- 「TP1（91-180日）の利益保持率(%)」のように日数帯を併記。

---

## 3) SKUタグから 3/6/9 プロファイルを決定

対象:
- `python/services/repricer_weekly.py`（または専用ヘルパー）

実装方針:
- SKU文字列から `-3-` / `-6-` / `-9-` のような判定をまず実装。
- 既存の3-6-9コード運用（`3P/3N/6P/6N/9P/9N`）がSKU内に入る場合も判定対象にする。
- 判定不可時は `default_profile` を適用し、理由欄に `PROFILE_FALLBACK` を残す（デバッグ用）。

---

## 4) 価格計算ロジック（ざっくり引き直し）

対象:
- `python/services/repricer_weekly.py`
- 必要なら Keepa値を受け取る中間処理

必要な入力（1SKU）:
- 現在価格 `current_price`
- 経過日数 `days_since_listed`
- TP下限 `tp_floor`（現在クォーターのTP）
- 直近同コンディション最安 `keepa_min`
- 間隔日数 `interval_days`
- 現在クォーターの終了日（TP1なら180）

ロジック:

1. `keepa_min < tp_floor`  
   - `new_price = tp_floor`
   - `reason` にアラート文言追加  
     例: `ALERT: keepa_min(2400) < TP1_floor(2500) のためTP下限で固定`

2. `keepa_min >= tp_floor`  
   - `start_price = min(current_price, keepa_min)`  
   - `remaining_days = period_end - days_since_listed`  
   - `steps = max(1, ceil(remaining_days / interval_days))`  
   - `delta = (start_price - tp_floor) / steps`  
   - `new_price = max(tp_floor, round(start_price - delta))`

補足:
- 毎回この計算を実行して引き直し（厳密等間隔は不要）。
- 価格上げは基本しない（`min(current_price, keepa_min)` を維持）。

---

## 5) アラートは理由欄に出す

対象:
- `python/services/repricer_weekly.py`（`reason` 文字列）
- `python/desktop/ui/repricer_widget.py`（既存の理由表示利用）

要件:
- 追加列なし。`reason` に明示文字列を入れる。
- 例:
  - `ALERT: keepa_min < TP下限。TP下限固定で停止`
  - `PROFILE_FALLBACK: SKUタグ判定不可のため6ルール適用`

---

## 6) Keepa最安値の取得・受け渡し

現状の `repricer` フローでは Keepa最安値を直接使っていないため、下記いずれかで実装:

- A. 改定対象CSVに `keepa_min_same_condition` 列を事前付与して渡す（推奨）
- B. 改定時にASINごとにKeepa問い合わせ（重くなるので非推奨）

初期実装はAを推奨。  
将来的にバッチ事前取得（仕入DB更新タイミング）へ拡張。

---

## 実装対象ファイル（優先順）

1. `python/desktop/ui/repricer_settings_widget.py`
2. `python/routers/repricer.py`
3. `python/services/repricer_weekly.py`
4. `config/reprice_rules.json`（マイグレーション対応）
5. 必要に応じて  
   - `python/desktop/ui/repricer_widget.py`（アラート表示の強調）
   - Keepa受け渡し関連（新規ヘルパー）

---

## 受け入れ基準（DoD）

1. `3-6-9価格改定 > 改定ルール` で `3/6/9` サブタブ表示ができる。
2. 各タブで TP利益保持率を保存・再読込できる。
3. SKUタグに応じて 3/6/9 ルールが切り替わる。
4. `keepa_min < tp_floor` のSKUは価格が `tp_floor` 未満にならない。
5. 上記SKUは結果テーブルの `理由` 列に `ALERT` が表示される。
6. `keepa_min >= tp_floor` のSKUは、残日数と `interval_days` に応じて  
   ざっくり引き直しで段階的に `tp_floor` へ近づく。
7. 既存の通常価格改定タブ（非3-6-9）に回帰不具合がない。

---

## 最低限の動作確認シナリオ

1. **3タグSKU / TP1期間 / keepa_min高め**
   - current=3000, tp_floor=2500, keepa_min=2600, interval=7
   - 改定価格が 2600付近から2500へ寄る方向になること

2. **3タグSKU / TP1期間 / keepa_min下回り**
   - current=3000, tp_floor=2500, keepa_min=2400
   - 改定価格=2500固定、理由にALERTが出ること

3. **6タグSKU / 6ルール適用確認**
   - 3ルールと別のTP率で結果が変わること

4. **タグ不明SKU**
   - default_profile適用、理由にフォールバック表示

---

## 次チャット用の貼り付けテンプレ（そのまま使える）

以下を次チャットの最初に貼る:

```text
docs/handover_3_6_9_reprice_agent.md の仕様どおりに実装してください。
対象は 3-6-9価格改定タブ側です。
既存の通常価格改定タブへの影響は避け、後方互換を保ってください。
実装後は、最低限の動作確認シナリオ4件を実行して結果を報告してください。
```

---

## 補足（運用）

- `keepa_min < TP下限` は **自動で下げない** のが運用確定。
- 必要なSKUだけ、ユーザーが目視でTP価格・販売価格を手動調整する。
- この方針で、突発安値に引っ張られる利益毀損を防ぐ。


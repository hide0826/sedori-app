# SP-API 取得ロール一覧（HIRIO）

更新日: 2026-08-13  
確認元: Seller Central → 開発者プロフィール「HMKstoreのプロフィール」

再確認が面倒なときは **このファイルを見れば足ります**。  
Amazon 側でロールを追加・変更したら、ここも更新してください。

---

## アプリ情報

| 項目 | 値 |
|------|-----|
| 開発者プロフィール | HMKstore |
| 本番アプリ名 | **HIRIO** |
| サンドボックスアプリ | なし |
| データアクセス | プライベート開発者（自社統合用） |
| マーケットプレイス（既定） | 日本 `A1VC38T7YXB528` |

---

## 承認済みロール（APPROVED）

| # | Seller Central 表示名 | 英語名（公式） | 主な用途 | HIRIO での状態 |
|---|----------------------|----------------|----------|----------------|
| 1 | **商品の出品** | Product Listing | Listings Items API（出品の取得・更新） | 仕入DB「SP-API取得」で出品日取得。watcher 出品制限もあり |
| 2 | **料金** | Pricing | Product Pricing / Fees | 仕入DBで手数料・FBA出荷費用見積を取得。価格改定は SP-API改定タブ⑤（Listings PATCH） |
| 3 | **在庫と注文の追跡** | Inventory and Order Tracking | 在庫・注文の取得 | 販売DB「SP-API更新」＋返品取込。出品一覧は SP-API改定タブ①（Reports）。保管料は未実装 |

※ 返金の**実額明細**（Finances API）には **財務と会計** ロールが別途必要（現状未承認 → レポート推定で運用）

---

## 仕入DBへの反映（2026-08-12〜）

データベース管理 > 仕入DB の **「SP-API取得」** ボタン。

- 行を選択している → 選択行のうち **出品日が空** のもの
- 未選択 → Amazon チャネルのうち **出品日が空** の全件（確認ダイアログあり。キャンセル可）
- 出品日が既にある行はスキップ（再取得しない）

| 仕入DB列 | SP-API | ロール |
|----------|--------|--------|
| 出品日 | Listings Items `summaries.createdDate` | 商品の出品 |
| プラットフォーム手数料 | Product Fees `ReferralFee` 等 | 料金 / 商品の出品 |
| 出荷費用 | Product Fees `FBAFees`（FBAのみ） | 料金 / 商品の出品 |

自己発送の出荷費用は Amazon から取れないため上書きしない。
`SP_API_SELLER_ID`（または設定タブの出品者ID）が必要。

---

## 販売DBへの反映（2026-08-13〜）

データベース管理 > 商品DB > 販売DB の **「SP-API更新」** ボタン。

- 過去 N 日（画面で指定、既定30・最大180）の注文を Orders API で取得
- 対象ステータス: Unshipped / PartiallyShipped / Shipped / InvoiceUnconfirmed（Pending・Canceled 除外）
- 販売DBへ差分 upsert（注文ID+SKU で重複判定）
- 取込後に仕入DBを数量突合し **販売済み** / **一部販売済み** に更新

| 販売DB列 | SP-API |
|----------|--------|
| 販売日 | `PurchaseDate` |
| SKU | OrderItems `SellerSKU` |
| 販売価格 | OrderItems `ItemPrice`（行合計） |
| 個数 | `QuantityOrdered` |
| 注文ID | `AmazonOrderId` |
| 配送経路 | `FulfillmentChannel`（AFN→FBA） |

手数料は注文APIに含まれないため、**仕入DBのプラットフォーム手数料・出荷費用・仕入れ価格から利益を計算**して埋める。Amazon実額の手数料は CSV 取込でも上書き可能。

### 返品・返金取込（2026-08-13〜）

販売DBの **「返品・返金取込」** ボタン。

- FBA返品レポート `GET_FBA_FULFILLMENT_CUSTOMER_RETURNS_DATA`（料金ロールで可）
- 返品フラットファイル `GET_FLAT_FILE_RETURNS_DATA_BY_RETURN_DATE`（在庫と注文の追跡で可・`Refunded Amount` あり）
- 注文ID+SKU で販売DBを突き合わせ、`返金総額` と利益を更新
- Finances API（返金実額）は **財務と会計ロールが必要**。未許可時はレポート＋販売価格から推定

---

## 申請時ユースケース（要約）

- 自社向けの在庫管理・**価格改定システム**の構築
- **Product Pricing API** / **Listings Items API** で相場取得と利益ロジックに基づく価格更新
- **Inventory API** で FBA・自社発送在庫の追跡
- **Orders API** で販売実績の取込と仕入ステータス連動

---

## 認証情報の置き場所

| 変数 | 場所 |
|------|------|
| `SP_API_CLIENT_ID` | `repo/sedori-app.github/.env` |
| `SP_API_CLIENT_SECRET` | 同上 |
| `SP_API_REFRESH_TOKEN` | 同上 |
| `SP_API_SELLER_ID` | 同上（未設定ならデスクトップ設定 `amazon/seller_id`） |

読み込み: `shared/amazon_credentials.py` → `shared/sp_api_client.py`

---

## 接続テスト（HIRIO 本体）

デスクトップアプリ → **SP-APIテスト** タブ

- `.env` 確認
- LWA トークン取得
- `marketplaceParticipations` 疎通
- Catalog API 1件テスト

※ 上記が通っても、**料金・出品の書き込みロールが使えることの証明にはならない**（読み取り系テストのみ）。

---

## 実装予定（`feature/sp-api`）

| 優先 | 機能 | 使うロール |
|------|------|------------|
| 1 | 仕入DBの出品日・手数料・出荷費用取得 | 商品の出品 + 料金（実装済） |
| 2 | 販売DBの注文取込＋仕入販売済み連動 | 在庫と注文の追跡（実装済） |
| 3 | 販売DBの返品・返金取込 | 料金 + 在庫と注文の追跡（実装済・Finances実額は財務ロール待ち） |
| 4 | **在庫・出品同期**（改定の入口。プライスターCSV代替） | 在庫と注文の追跡 + 商品の出品（**SP-API改定タブ①で実装済**） |
| 5 | 価格改定の API 反映（改定の出口。Listings PATCH 等） | 料金 + 商品の出品（**SP-API改定タブ⑤で実装済・試験N件制限あり**） |
| 6 | **同コンディション最安追従**（150日境界・自動巡回） | 料金（Offers）+ 商品の出品（PATCH） |
| — | 返金実額（Finances） | 財務と会計（未承認） |

※ 2026-08-13 方針: 価格改定の自動化は「出口の価格 PATCH」だけでは不十分。  
**Amazonの最新在庫・出品を取得 → 仕入DBと突合 → 既存ルール計算 → 価格反映** の閉じたループが前提。  
そのため旧「4=価格反映 / 5=在庫同期」を入れ替え、在庫・出品同期を先にする。  
※ 同日実装: 価格改定 > **SP-API改定** タブ（既存「改定実行」は非破壊で維持）。

---

## 再確認が必要なとき

Seller Central でロールを変更した場合のみ:

1. [開発者コンソール](https://sellercentral.amazon.co.jp/sellingpartner/developerconsole)
2. **HMKstoreのプロフィール** → データアクセス → ロール一覧
3. このファイルを更新

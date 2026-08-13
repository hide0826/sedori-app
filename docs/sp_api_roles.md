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
| 2 | **料金** | Pricing | Product Pricing / Fees | 仕入DBで手数料・FBA出荷費用見積を取得。価格改定 API 反映は未実装 |
| 3 | **在庫と注文の追跡** | Inventory and Order Tracking | 在庫・注文の取得 | **未実装**（保管料レポート等は後回し） |

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

## 申請時ユースケース（要約）

- 自社向けの在庫管理・**価格改定システム**の構築
- **Product Pricing API** / **Listings Items API** で相場取得と利益ロジックに基づく価格更新
- **Inventory API** で FBA・自社発送在庫の追跡

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
| 1 | 仕入DBの出品日・手数料・出荷費用取得 | 商品の出品 + 料金 |
| 2 | 価格改定の API 反映 | 料金 + 商品の出品 |
| 3 | 在庫同期 | 在庫と注文の追跡 |
| 4 | 注文取込 | 在庫と注文の追跡 |

---

## 再確認が必要なとき

Seller Central でロールを変更した場合のみ:

1. [開発者コンソール](https://sellercentral.amazon.co.jp/sellingpartner/developerconsole)
2. **HMKstoreのプロフィール** → データアクセス → ロール一覧
3. このファイルを更新

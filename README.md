[![Latest release](https://img.shields.io/github/v/release/hide0826/sedori-app?display_name=tag&sort=semver)](https://github.com/hide0826/sedori-app/releases)
[![CI](https://img.shields.io/github/actions/workflow/status/hide0826/sedori-app/progress-update.yml?label=CI)](https://github.com/hide0826/sedori-app/actions)

# せどり事業自動化アプリ (HIRIO) — v0.3.3

`sedori-app` は、中古店舗せどりの事務作業を自動化するための Python アプリです。  
CSV の検査・正規化・一括処理を API で提供し、Excel 依存を脱却して処理速度・再現性を高めます。

---

## 主な機能
- **/csv/inspect**: 文字コード・区切り推定、ヘッダー検出、サンプル表示  
  - `?clean=true` … 前処理クリーニングを適用（全角/不可視/ダッシュ統一 等）  
  - `?check_ean13=true` … `ean13_*` の計算/検証列を付与
- **/csv/normalize**: 列マッピング・必須列チェック・並び替え・クリーニング・レポート出力  
  - `dry_run=true` … 出力ファイルは書かず **レポートのみ** を生成  
- **/csv/bulk_normalize**: ディレクトリ一括処理（プレビュー/レポート集計）

## プリセット
- `sedori_basic`（基本）
- `amazon_jp`
- `mercari`
- `yahoo_shopping`  
いずれも `header_map / required_headers / order` を内包。  
リクエスト側で `header_map` を渡すと **プリセットより優先** されます。

## 使い方（PowerShell）
```powershell
$h=@{Authorization="Bearer hirio-local-key"}
$base="http://127.0.0.1:17660"

# inspect（クリーニング + EAN-13 検証）
$body = @{ preset="sedori_basic"; relpath="test_ean13.csv"; encoding_in="utf-8-sig" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$base/csv/inspect?clean=true&check_ean13=true" -Headers $h -ContentType "application/json" -Body $body

# normalize（dry_run + レポート CSV）
$body = @{
  preset="sedori_basic"; relpath_in="test_ean13.csv"; relpath_out="test_ean13__out.csv";
  dry_run=$true; encoding_in="utf-8-sig"; report_relpath="test_ean13__report.csv"
} | ConvertTo-Json -Depth 6
Invoke-RestMethod -Method Post -Uri "$base/csv/normalize?clean=true&check_ean13=true" -Headers $h -ContentType "application/json" -Body $body


### 変更点
- feat(clean): クリーニング後の値で EAN-13 検証（全角/不可視/ダッシュ混入の誤NG解消）
- docs: presets（sedori_basic / amazon_jp / mercari / yahoo_shopping）追記
- chore: health 表示/バージョン識別の改善

### 影響
- /csv/inspect?clean=true&check_ean13=true の sample 正規化
- /csv/normalize?clean=true&check_ean13=true のレポートで全角JANの誤NG解消

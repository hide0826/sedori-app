# HIRIO PySide6 デスクトップアプリ - 引き継ぎドキュメント

## 📋 プロジェクト概要
- **目標**: PWAからPySide6デスクトップアプリへの移行
- **技術スタック**: PySide6 + FastAPI + SQLite
- **現在の進捗**: 価格改定機能の実装完了
- **次フェーズ**: 仕入管理システムの実装

## ✅ 完了した機能

### 1. 価格改定機能（RepricerWidget）
**ファイル**: `python/desktop/ui/repricer_widget.py`

#### 実装済み機能
- ✅ CSVファイル選択（設定のデフォルトディレクトリ対応）
- ✅ CSV内容自動プレビュー（ファイル選択時に自動表示）
- ✅ 価格改定プレビュー
- ✅ 価格改定実行
- ✅ 結果のCSV保存（変更のないSKUは除外）
- ✅ ソート機能（全列に対応、数値ソート実装）
- ✅ Trace変更の日本語表示（0=維持、1=FBA状態合わせ、2=状態合わせ、3=FBA最安値、4=最安値、5=カート価格）

#### 主要クラス
- `NumericTableWidgetItem`: 数値ソート用のカスタムItem
- `RepricerWorker`: 非同期処理用のワーカースレッド
- `RepricerWidget`: メインウィジェット

#### 技術的特徴
- 設定からのデフォルトディレクトリ読み込み（QSettings使用）
- マルチスレッド処理（QThread使用）
- 数値ソートの実装（`__lt__`メソッドのオーバーライド）
- エラーハンドリング（ErrorHandler使用）
- Excel数式記法の自動クリーンアップ

### 2. バックエンドAPI統合
**ファイル**: `python/routers/repricer.py`, `python/services/repricer_weekly.py`

#### 実装済みエンドポイント
- `/repricer/preview`: 価格改定プレビュー
- `/repricer/apply`: 価格改定実行

#### 主な機能
- priceTraceChangeフィールドの追加
- 除外CSV生成機能
- ログ出力機能

### 3. 設定機能
**ファイル**: `python/desktop/ui/settings_widget.py`

#### 実装済み設定
- CSVファイル用ディレクトリ
- 結果ファイル用ディレクトリ
- QSettingsによる永続化

## 🔧 技術的な実装詳細

### 1. 数値ソートの実装
```python
class NumericTableWidgetItem(QTableWidgetItem):
    """数値ソート用のカスタムTableWidgetItem"""
    
    def __init__(self, value):
        super().__init__()
        self.numeric_value = float(value) if value else 0.0
    
    def __lt__(self, other):
        """小なり演算子をオーバーライドして数値比較を実装"""
        if isinstance(other, NumericTableWidgetItem):
            return self.numeric_value < other.numeric_value
        return super().__lt__(other)
```

### 2. 設定からのディレクトリ読み込み
```python
# 初期化時にQSettingsを設定
self.settings = QSettings("HIRIO", "DesktopApp")

# ファイル選択時に設定から読み込み
default_dir = self.settings.value("directories/csv", "")
```

### 3. 変更のないSKUの除外
```python
# 価格とpriceTraceの両方が変更されていない場合はスキップ
if new_price == original_price and new_price_trace == original_price_trace:
    print(f"[DEBUG CSV保存] スキップ: {sku} (変更なし)")
    continue
```

## 📂 ファイル構成
```
python/desktop/
├── main.py                          # エントリーポイント
├── api/
│   └── client.py                    # APIクライアント
└── ui/
    ├── main_window.py               # メインウィンドウ
    ├── repricer_widget.py           # 価格改定ウィジェット（主要）
    ├── settings_widget.py           # 設定ウィジェット
    └── ...

python/
├── routers/
│   └── repricer.py                  # 価格改定API
├── services/
│   └── repricer_weekly.py           # 価格改定ロジック
└── utils/
    ├── csv_io.py                    # CSV I/O
    └── error_handler.py             # エラーハンドリング
```

## 🎯 現在の動作状況
- ✅ バックエンドAPI: 正常動作（ポート8000）
- ✅ デスクトップアプリ: 正常動作
- ✅ 価格改定機能: 完全に機能
- ✅ ソート機能: 正常動作
- ✅ CSV保存: 正常動作（変更のないSKUは除外）

## 📝 次の実装タスク（優先度順）

### 1. 仕入管理システムの実装
- [ ] 在庫一覧表示機能
- [ ] 在庫検索機能
- [ ] 在庫更新機能
- [ ] CSVインポート機能
- [ ] CSVエクスポート機能

### 2. 古物管理機能
- [ ] 古物登録機能
- [ ] 古物一覧表示
- [ ] 古物更新機能
- [ ] 古物削除機能

### 3. ワークフロー機能
- [ ] ワークフロー定義
- [ ] ワークフロー実行
- [ ] ワークフロー履歴

## 🔍 トラブルシューティング

### よくある問題
1. **API接続エラー**
   - FastAPIサーバーが起動しているか確認
   - ポート8000が使用可能か確認

2. **ソートが効かない**
   - NumericTableWidgetItemを使用しているか確認
   - setSortingEnabled(True)が呼ばれているか確認

3. **CSV保存エラー**
   - ディレクトリの書き込み権限を確認
   - ファイルが他のアプリで開かれていないか確認

## 🚀 開発環境の起動方法

### 1. バックエンド起動
```bash
cd python
python app.py
```

### 2. デスクトップアプリ起動
```bash
cd python/desktop
python main.py
```

## 📊 データベース設計
（現在未実装、次フェーズで実装予定）

## 🎨 UI/UX の設計方針
- シンプルで直感的なインターフェース
- 初心者にもわかりやすい操作
- エラーメッセージの日本語化
- プログレスバーによる処理状況の可視化

## 📚 参考資料
- PySide6公式ドキュメント: https://doc.qt.io/qtforpython/
- FastAPI公式ドキュメント: https://fastapi.tiangolo.com/

## 🏁 まとめ
価格改定機能は完全に実装済みで、本番環境で使用可能な状態です。
次フェーズとして、仕入管理システムの実装に進むことができます。

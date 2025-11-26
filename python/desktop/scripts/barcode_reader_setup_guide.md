# バーコードリーダーセットアップガイド

## テスト結果

### ✓ 成功した項目
- **pyzbarモジュール**: インストール済み（バージョン 0.1.9）

### ✗ 問題がある項目
- **zbarライブラリ（DLL）**: 見つかりません
- **エラーメッセージ**: `Could not find module 'libzbar-64.dll' (or one of its dependencies)`

## 問題の原因

`pyzbar`はPythonパッケージとしてインストールされていますが、`zbar`ライブラリ本体（DLL）がWindowsシステムに見つかりません。

Windowsでは、`pyzbar`と`zbar`ライブラリは別々にインストールする必要があります。

## 解決方法（Windows）

### 方法1: zbar-w64を手動でダウンロード・インストール（推奨）

1. **zbar-w64のダウンロード**
   - https://sourceforge.net/projects/zbar/files/
   - または https://github.com/mchehab/zbar/releases
   - 最新のWindows用バイナリをダウンロード（例: `zbar-0.23.90-setup.exe`）

2. **インストール**
   - ダウンロードしたインストーラーを実行
   - インストール先をデフォルト（通常は `C:\Program Files\ZBar`）でインストール

3. **環境変数の設定（必要に応じて）**
   - システム環境変数 `Path` に zbar の bin ディレクトリを追加
   - 例: `C:\Program Files\ZBar\bin`

4. **Python環境へのリンク（オプション）**
   - `libzbar-64.dll` を `pyzbar` パッケージディレクトリにコピー
   - コピー先: `C:\Users\user\AppData\Local\Programs\Python\Python313\Lib\site-packages\pyzbar\`
   - コピー元: `C:\Program Files\ZBar\bin\libzbar-64.dll`

### 方法2: condaを使用（conda環境の場合）

```bash
conda install -c conda-forge zbar
```

## 動作確認

セットアップ後、以下のコマンドで動作確認してください：

```bash
cd python/desktop
python scripts/test_barcode_reader.py
```

すべてのテストが成功すれば、バーコードリーダーは正常に動作しています。

## トラブルシューティング

### DLLが見つからないエラーが続く場合

1. **DLLファイルの場所を確認**
   ```bash
   # zbarインストール先を確認
   dir "C:\Program Files\ZBar\bin\libzbar-64.dll"
   ```

2. **環境変数PATHを確認**
   - コントロールパネル > システム > 環境変数
   - `Path`にzbarのbinディレクトリが含まれているか確認

3. **Python環境に直接DLLをコピー**
   ```bash
   # 管理者権限で実行
   copy "C:\Program Files\ZBar\bin\libzbar-64.dll" "C:\Users\user\AppData\Local\Programs\Python\Python313\Lib\site-packages\pyzbar\"
   ```

### 依存関係のエラーが出る場合

- Visual C++ Redistributableが必要な場合があります
- https://aka.ms/vs/17/release/vc_redist.x64.exe からダウンロードしてインストール

## 参考リンク

- pyzbar公式: https://github.com/NuGet/pyzbar
- zbar公式: http://zbar.sourceforge.net/
- Windowsバイナリ: https://sourceforge.net/projects/zbar/files/





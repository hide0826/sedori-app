# レシートOCRテストスクリプト

## 使い方

### 方法1: バッチファイルをダブルクリック（最も簡単）

1. `test_receipt_ocr_simple.bat` をダブルクリック
2. 画像ファイルのパスを入力
3. Enterキーを押す

### 方法2: 画像ファイルをドラッグ&ドロップ

1. `test_receipt_ocr.bat` または `test_receipt_ocr_batch.bat` に画像ファイルをドラッグ&ドロップ
2. 自動的にOCRが実行されます

### 方法3: PowerShellから実行

```powershell
cd python\scripts
.\test_receipt_ocr_simple.bat
```

または

```powershell
cd python
python scripts\test_receipt_ocr_simple.py
```

## トラブルシューティング

### PowerShellがすぐ閉じる場合

バッチファイル（`.bat`）を使用してください。バッチファイルには `pause` コマンドが含まれているため、エラー時も画面が閉じません。

### エラーが表示されない場合

1. バッチファイルをダブルクリックして実行
2. または、PowerShellで以下のコマンドを実行：
   ```powershell
   cd python
   python scripts\test_receipt_ocr_simple.py
   ```
   実行後、エラーメッセージが表示されます。





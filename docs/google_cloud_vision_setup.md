# Google Cloud Vision API セットアップガイド

## 概要

Google Cloud Vision APIを導入することで、OCRの精度を大幅に向上させることができます。
Tesseract OCRで精度が低い場合のフォールバックとして使用できます。

## セットアップ手順

### 1. Google Cloud Platform（GCP）アカウントの作成

1. [Google Cloud Platform](https://cloud.google.com/) にアクセス
2. アカウントを作成（既にアカウントがある場合はスキップ）
3. 無料トライアルが利用可能（$300のクレジット、90日間）

### 2. プロジェクトの作成

1. GCPコンソールにログイン
2. プロジェクト選択メニューから「新しいプロジェクト」をクリック
3. プロジェクト名を入力（例: `hirio-ocr`）
4. 「作成」をクリック

### 3. Cloud Vision APIの有効化

1. 左メニューから「APIとサービス」→「ライブラリ」を選択
2. 「Cloud Vision API」を検索
3. 「Cloud Vision API」を選択して「有効にする」をクリック

### 4. サービスアカウントの作成

1. 左メニューから「APIとサービス」→「認証情報」を選択
2. 「認証情報を作成」→「サービスアカウント」を選択
3. サービスアカウント名を入力（例: `hirio-ocr-service`）
4. 「作成して続行」をクリック
5. ロールの選択（以下のいずれか）:
   - **推奨**: 「Cloud Vision AI サービス エージェント」（自動的に付与される）
   - または「エディタ」（より広い権限）
   - または「閲覧者」（最小限の権限、API使用には十分）
6. 「続行」をクリック（「ユーザーへのアクセス権の付与」はスキップ可能）
7. 「完了」をクリック

### 5. サービスアカウントキーの作成

1. 作成したサービスアカウントをクリック
2. 「キー」タブを選択
3. 「キーを追加」→「新しいキーを作成」を選択
4. キーのタイプは「JSON」を選択
5. 「作成」をクリック
6. JSONファイルがダウンロードされます（例: `hirio-ocr-xxxxx.json`）

**重要**: このJSONファイルは機密情報です。他人に共有しないでください。

#### 推奨保存場所

JSONファイルは以下の場所に保存することを推奨します：

**推奨パス（プロジェクト内）:**
```
D:\HIRIO\repo\sedori-app.github\python\desktop\data\credentials\
```

このフォルダは自動的に作成されますが、手動で作成する場合：

```powershell
# PowerShellで実行
mkdir D:\HIRIO\repo\sedori-app.github\python\desktop\data\credentials
```

または

**推奨パス（ユーザーディレクトリ）:**
```
C:\Users\YourName\Documents\HIRIO\credentials\
```

このフォルダも手動で作成してください。

**保存時の注意点:**
- プロジェクトのGitリポジトリにコミットしない（`.gitignore`に追加済み）
- ファイル名を分かりやすくする（例: `hirio-gcv-credentials.json`）
- バックアップを取る（USBメモリやクラウドストレージに暗号化して保存）

### 6. Pythonパッケージのインストール

```powershell
pip install google-cloud-vision
```

または、requirements.txtからインストール：

```powershell
pip install -r requirements.txt
```

### 7. アプリケーションでの設定

1. デスクトップアプリを起動
2. 「設定」タブ → 「詳細設定」 → 「OCR設定」を開く
3. 「GCV認証情報(JSON)」に、ダウンロードしたJSONファイルのパスを指定
   - 例: `D:\HIRIO\repo\sedori-app.github\python\desktop\data\credentials\hirio-gcv-credentials.json`
4. 「OCR設定テスト」ボタンをクリックして動作確認
5. 「設定を保存」をクリック

### 8. 動作確認方法

#### 方法1: 設定画面のテストボタン

1. 「設定」タブ → 「詳細設定」 → 「OCR設定」
2. 「OCR設定テスト」ボタンをクリック
3. 「Tesseract設定は正常です」または「GCV設定は正常です」と表示されればOK

#### 方法2: 実際の画像でテスト（推奨）

**バッチファイルを使用:**
1. `python/scripts/test_gcv_ocr.bat` に画像ファイルをドラッグ&ドロップ
2. または、コマンドラインで実行：
   ```powershell
   cd python
   python scripts\test_gcv_ocr.py "D:\receipts\receipt.jpg"
   ```

**確認ポイント:**
- 「プロバイダ: gcv」と表示されれば、Google Cloud Vision APIが使用されています
- 「プロバイダ: tesseract」と表示される場合は、GCVの設定を確認してください
- OCR結果の精度が大幅に向上しているはずです

#### 方法3: レシート管理タブでテスト

1. デスクトップアプリの「レシート管理」タブを開く
2. 「画像を選択」ボタンでレシート画像を選択
3. OCR実行後、抽出されたテキストの精度を確認
4. 日付・店舗名・金額などが正しく抽出されていれば成功

### 8. 使用方法

設定後、レシート管理タブや保証書管理タブで画像をアップロードすると、
自動的にGoogle Cloud Vision APIが使用されます（Tesseractが失敗した場合）。

または、OCRServiceの初期化時に`gcv_credentials_path`を指定することで、
直接使用することもできます。

## 料金について

- **無料枠**: 月1,000リクエストまで無料
- **有料**: 1,000リクエストを超えると、1,000リクエストあたり$1.50
- 詳細: https://cloud.google.com/vision/pricing

## トラブルシューティング

### エラー: "Could not automatically determine credentials"

- JSONファイルのパスが正しいか確認
- 環境変数`GOOGLE_APPLICATION_CREDENTIALS`が設定されているか確認
- JSONファイルの内容が正しいか確認

### エラー: "Permission denied"

- サービスアカウントに適切なロールが付与されているか確認
  - 「Cloud Vision AI サービス エージェント」（自動付与）
  - または「エディタ」「閲覧者」など
- APIが有効になっているか確認

### エラー: "API not enabled"

- Cloud Vision APIが有効になっているか確認
- 正しいプロジェクトが選択されているか確認

## 参考リンク

- [Google Cloud Vision API ドキュメント](https://cloud.google.com/vision/docs)
- [Python クライアントライブラリ](https://cloud.google.com/vision/docs/libraries#client-libraries)
- [料金情報](https://cloud.google.com/vision/pricing)


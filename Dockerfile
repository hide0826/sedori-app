# ベースイメージとして公式のPython 3.11スリム版を使用
FROM python:3.11-slim

# 環境変数設定
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# 作業ディレクトリを作成・設定
WORKDIR /app

# PYTHONPATHを設定して、プロジェクトルートからのインポートを有効にする
ENV PYTHONPATH=/app

# 依存関係ファイルをコピーし、インストール
# requirements.txtだけを先にコピーすることで、Dockerのレイヤーキャッシュを有効活用する
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# プロジェクトのソースコードはdocker-compose.ymlのvolumesでマウントする

# FastAPIサーバーを起動するコマンド
# 0.0.0.0で待ち受けることで、コンテナ外からのアクセスを許可する
# --reloadオプションを復元
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

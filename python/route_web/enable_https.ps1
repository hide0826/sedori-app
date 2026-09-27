# ルート時刻Web（127.0.0.1:8792）を、Tailscale の https で公開する。
# スマホの連続撮影（ページ内カメラ）は、この https アドレスで開いたときだけ動く。
# LAN の http://192.168.0.200:8792 はそのまま残る。
# Tailscale を掴んでいる Windows ユーザー（houseserver\takem）で実行する。

$exe = "C:\Program Files\Tailscale\tailscale.exe"
if (-not (Test-Path $exe)) {
    Write-Error "Tailscale が見つかりません: $exe"
    exit 1
}

& $exe serve --bg --yes 8792
if ($LASTEXITCODE -ne 0) {
    Write-Error "https の設定に失敗しました。Tailscale 管理画面で HTTPS 証明書を有効にしてから、もう一度実行してください。"
    exit $LASTEXITCODE
}

& $exe serve status
Write-Host ""
Write-Host "上に出た https://....ts.net をスマホで開いてください。"

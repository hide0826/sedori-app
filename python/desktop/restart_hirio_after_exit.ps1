param(
    [Parameter(Mandatory = $true)][int]$WaitPid,
    [Parameter(Mandatory = $true)][string]$BatPath
)

while (Get-Process -Id $WaitPid -ErrorAction SilentlyContinue) {
    Start-Sleep -Seconds 2
}
Start-Sleep -Seconds 2
if (Test-Path -LiteralPath $BatPath) {
    Start-Process -FilePath $BatPath
}

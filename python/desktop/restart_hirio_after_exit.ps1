param(
    [Parameter(Mandatory = $true)][int]$WaitPid,
    [Parameter(Mandatory = $true)][string]$BatPath,
    [string]$LogPath = ""
)

function Write-RestartLog([string]$Message) {
    if (-not $LogPath) { return }
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    try {
        $dir = Split-Path -Parent $LogPath
        if ($dir -and -not (Test-Path -LiteralPath $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
        Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
    } catch {}
}

Write-RestartLog "waiter start pid=$WaitPid bat=$BatPath"
while (Get-Process -Id $WaitPid -ErrorAction SilentlyContinue) {
    Start-Sleep -Seconds 2
}
Start-Sleep -Seconds 2
if (-not (Test-Path -LiteralPath $BatPath)) {
    Write-RestartLog "bat missing: $BatPath"
    exit 1
}
try {
    $work = Split-Path -Parent $BatPath
    $proc = Start-Process -FilePath $BatPath -WorkingDirectory $work -PassThru
    Write-RestartLog "relaunched pid=$($proc.Id)"
} catch {
    Write-RestartLog "relaunch failed: $($_.Exception.Message)"
    exit 1
}

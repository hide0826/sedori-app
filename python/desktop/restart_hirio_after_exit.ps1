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

function Clear-BusyFlag {
    if (-not $LogPath) { return }
    $busy = Join-Path (Split-Path -Parent $LogPath) "nightly_restart.busy"
    if (Test-Path -LiteralPath $busy) {
        Remove-Item -LiteralPath $busy -Force -ErrorAction SilentlyContinue
        Write-RestartLog "cleared busy flag"
    }
}

function Test-DesktopRunning {
    $hits = @(
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {
                $_.CommandLine -and
                (
                    $_.CommandLine -like "*python\desktop\main.py*" -or
                    $_.CommandLine -like "*python/desktop/main.py*" -or
                    $_.CommandLine -like "*desktop\main.py*" -or
                    $_.CommandLine -like "*desktop/main.py*"
                )
            }
    )
    return ($hits.Count -gt 0)
}

Write-RestartLog "waiter start pid=$WaitPid bat=$BatPath"
$deadline = (Get-Date).AddMinutes(30)
while (Get-Process -Id $WaitPid -ErrorAction SilentlyContinue) {
    if ((Get-Date) -gt $deadline) {
        Write-RestartLog "wait timeout for pid=$WaitPid; continue anyway"
        break
    }
    Start-Sleep -Seconds 2
}
Start-Sleep -Seconds 2
if (-not (Test-Path -LiteralPath $BatPath)) {
    Write-RestartLog "bat missing: $BatPath"
    Clear-BusyFlag
    exit 1
}
try {
    $work = Split-Path -Parent $BatPath
    $proc = Start-Process -FilePath $BatPath -WorkingDirectory $work -PassThru
    Write-RestartLog "relaunched pid=$($proc.Id)"
} catch {
    Write-RestartLog "relaunch failed: $($_.Exception.Message)"
    # 番人（watch_hirio_desktop）に任せるため busy を消す
    Clear-BusyFlag
    exit 1
}

# 起動確認（最大約90秒）。成功時は busy は新プロセス側で消す。
# 失敗時だけ busy を消して番人に引き継ぐ。
$ok = $false
for ($i = 0; $i -lt 18; $i++) {
    Start-Sleep -Seconds 5
    if (Test-DesktopRunning) {
        $ok = $true
        break
    }
}
if ($ok) {
    Write-RestartLog "desktop process confirmed"
} else {
    Write-RestartLog "desktop process not seen; clear busy for watchdog"
    Clear-BusyFlag
}

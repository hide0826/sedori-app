#Requires -Version 5.1
<#
.SYNOPSIS
  Watchdog for HIRIO desktop GUI (python\desktop\main.py).
  If the app is not running, start start_hirio.bat.

  Skips while a nightly restart is in progress (busy flag, up to 15 min).
  Skips when desktop.paused exists (intentional stop).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\watch_hirio_desktop.ps1
  powershell -ExecutionPolicy Bypass -File .\watch_hirio_desktop.ps1 -Install
#>
param(
    [switch]$Install
)

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Repo = Split-Path (Split-Path $ScriptDir -Parent) -Parent
$Bat = Join-Path $Repo "start_hirio.bat"
$LogDir = Join-Path $ScriptDir "logs"
$Log = Join-Path $LogDir "desktop_watchdog.log"
$BusyFlag = Join-Path $LogDir "nightly_restart.busy"
$PauseFlag = Join-Path $ScriptDir "desktop.paused"
$TaskName = "HIRIO_desktop"
$BusyGraceMinutes = 15
$PollSeconds = 20

function Write-WatchLog([string]$Message) {
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    try {
        if (-not (Test-Path $LogDir)) {
            New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
        }
        if ((Test-Path $Log) -and ((Get-Item $Log).Length -gt 512KB)) {
            Remove-Item $Log -Force -ErrorAction SilentlyContinue
        }
        Add-Content -Path $Log -Value $line -Encoding UTF8
    } catch {}
    Write-Host $line
}

function Get-WatchProcesses {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine -like "*watch_hirio_desktop.ps1*" -and
            $_.CommandLine -notlike "*-Install*"
        }
}

function Get-AppProcesses {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and
            (
                $_.CommandLine -like "*python\desktop\main.py*" -or
                $_.CommandLine -like "*python/desktop/main.py*" -or
                $_.CommandLine -like "*desktop\main.py*" -or
                $_.CommandLine -like "*desktop/main.py*"
            ) -and
            $_.CommandLine -notlike "*watch_hirio_desktop*"
        }
}

function Test-AppRunning {
    return (@(Get-AppProcesses).Count -gt 0)
}

function Test-NightlyBusy {
    if (-not (Test-Path -LiteralPath $BusyFlag)) {
        return $false
    }
    try {
        $age = (Get-Date) - (Get-Item -LiteralPath $BusyFlag).LastWriteTime
        if ($age.TotalMinutes -lt $BusyGraceMinutes) {
            return $true
        }
        Write-WatchLog ("nightly busy flag stale ({0:N0} min) -> clear" -f $age.TotalMinutes)
        Remove-Item -LiteralPath $BusyFlag -Force -ErrorAction SilentlyContinue
    } catch {
        Remove-Item -LiteralPath $BusyFlag -Force -ErrorAction SilentlyContinue
    }
    return $false
}

function Start-HirioDesktop {
    if (-not (Test-Path -LiteralPath $Bat)) {
        Write-WatchLog "bat missing: $Bat"
        return
    }
    Write-WatchLog "desktop not running -> start_hirio.bat"
    try {
        Start-Process -FilePath $Bat -WorkingDirectory $Repo | Out-Null
    } catch {
        Write-WatchLog "start failed: $($_.Exception.Message)"
    }
}

function Install-WatchTask {
    $script = Join-Path $ScriptDir "watch_hirio_desktop.ps1"
    $ps = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $action = New-ScheduledTaskAction `
        -Execute $ps `
        -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`"" `
        -WorkingDirectory $ScriptDir
    $triggerLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $triggerStartup = New-ScheduledTaskTrigger -AtStartup
    $triggerStartup.Delay = "PT3M"
    $triggerRepeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
        -RepetitionInterval (New-TimeSpan -Minutes 5) `
        -RepetitionDuration (New-TimeSpan -Days 3650)
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -DontStopOnIdleEnd `
        -StartWhenAvailable `
        -MultipleInstances IgnoreNew `
        -RestartCount 999 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit ([TimeSpan]::Zero)
    # GUI needs an interactive desktop session
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger @($triggerStartup, $triggerLogon, $triggerRepeat) `
        -Settings $settings `
        -Principal $principal `
        -Force | Out-Null
    Write-WatchLog "Registered task $TaskName (startup+logon+5min)"
    Write-Host "Manual start: Start-ScheduledTask -TaskName `"$TaskName`""
    Write-Host "Pause: create $PauseFlag"
    Write-Host "Resume: remove $PauseFlag"
}

if ($Install) {
    Install-WatchTask
    exit 0
}

$others = @(Get-WatchProcesses | Where-Object { $_.ProcessId -ne $PID })
if ($others.Count -gt 0) {
    Write-WatchLog "another watchdog already running (pid=$($others[0].ProcessId)); exit"
    exit 0
}

if (-not (Test-Path -LiteralPath $Bat)) {
    Write-WatchLog "bat missing: $Bat"
    exit 1
}

Write-WatchLog "watchdog start (desktop GUI)"
while ($true) {
    if (Test-Path -LiteralPath $PauseFlag) {
        Start-Sleep -Seconds $PollSeconds
        continue
    }
    if (Test-NightlyBusy) {
        Start-Sleep -Seconds $PollSeconds
        continue
    }
    if (-not (Test-AppRunning)) {
        Start-HirioDesktop
        Start-Sleep -Seconds 25
    }
    Start-Sleep -Seconds $PollSeconds
}

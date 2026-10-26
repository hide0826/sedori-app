#Requires -Version 5.1
<#
.SYNOPSIS
  Register unattended SP-API tasks:
    HIRIO_reprice_weekly_369  - Sunday 04:00
    HIRIO_reprice_follow      - every 8 hours
    HIRIO_sp_api_daily_sync   - every day 09:00

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install_sp_api_reprice_tasks.ps1
  powershell -ExecutionPolicy Bypass -File .\install_sp_api_reprice_tasks.ps1 -DailySyncOnly
#>
param(
    [switch]$DryRunDefault,
    [switch]$DailySyncOnly,
    [int]$MaxPatch = 0
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DesktopDir = Split-Path -Parent $ScriptDir
$PythonDir = Split-Path -Parent $DesktopDir
$Repo = Split-Path -Parent $PythonDir
$PythonExe = Join-Path $Repo ".venv\Scripts\python.exe"
$JobScript = Join-Path $ScriptDir "run_sp_api_reprice_job.py"
$DailyScript = Join-Path $ScriptDir "run_sp_api_daily_sync_job.py"
$Ps = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "venv python missing: $PythonExe"
}
if (-not (Test-Path -LiteralPath $JobScript)) {
    throw "job script missing: $JobScript"
}

function New-HirioRepriceTask {
    param(
        [string]$TaskName,
        [string]$Mode,
        [object[]]$Triggers,
        [bool]$UseDryRun,
        [int]$PatchLimit = 0
    )
    $dry = if ($UseDryRun) { " --dry-run" } else { "" }
    $limit = if ((-not $UseDryRun) -and $PatchLimit -gt 0) { " --max-patch $PatchLimit" } else { "" }
    $argList = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command `"& '$PythonExe' '$JobScript' --mode $Mode$dry$limit`""
    $action = New-ScheduledTaskAction -Execute $Ps -Argument $argList -WorkingDirectory $Repo
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -DontStopOnIdleEnd `
        -StartWhenAvailable `
        -MultipleInstances IgnoreNew `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 5) `
        -ExecutionTimeLimit (New-TimeSpan -Hours 8)
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $Triggers `
        -Settings $settings `
        -Principal $principal `
        -Force | Out-Null
    Write-Host "Registered $TaskName (mode=$Mode dryRun=$UseDryRun)"
}

function Register-HirioDailySyncTask {
    if (-not (Test-Path -LiteralPath $DailyScript)) {
        throw "daily sync script missing: $DailyScript"
    }
    $argList = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command `"& '$PythonExe' '$DailyScript'`""
    $action = New-ScheduledTaskAction -Execute $Ps -Argument $argList -WorkingDirectory $Repo
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -DontStopOnIdleEnd `
        -StartWhenAvailable `
        -MultipleInstances IgnoreNew `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 5) `
        -ExecutionTimeLimit (New-TimeSpan -Hours 8)
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
    $trigger = New-ScheduledTaskTrigger -Daily -At 9:00AM
    Register-ScheduledTask `
        -TaskName "HIRIO_sp_api_daily_sync" `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Force | Out-Null
    Write-Host "Registered HIRIO_sp_api_daily_sync (daily 09:00)"
}

if ($DailySyncOnly) {
    Register-HirioDailySyncTask
    Write-Host "Log: $DesktopDir\logs\sp_api_daily_sync.log"
    return
}

$weeklyTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 4:00AM
$followTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) `
    -RepetitionInterval (New-TimeSpan -Hours 8) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

New-HirioRepriceTask -TaskName "HIRIO_reprice_weekly_369" -Mode "weekly369" -Triggers @($weeklyTrigger) -UseDryRun:$DryRunDefault -PatchLimit $MaxPatch
New-HirioRepriceTask -TaskName "HIRIO_reprice_follow" -Mode "follow" -Triggers @($followTrigger) -UseDryRun:$DryRunDefault -PatchLimit $MaxPatch
Register-HirioDailySyncTask

Write-Host ""
Write-Host "Manual:"
Write-Host "  Start-ScheduledTask -TaskName HIRIO_reprice_weekly_369"
Write-Host "  Start-ScheduledTask -TaskName HIRIO_reprice_follow"
Write-Host "  Start-ScheduledTask -TaskName HIRIO_sp_api_daily_sync"
Write-Host "Logs: $DesktopDir\logs\sp_api_reprice_*.log"
Write-Host "      $DesktopDir\logs\sp_api_daily_sync.log"
if ($DryRunDefault) {
    Write-Host "Dry-run is ON. After 1SKU Seller Central check:"
    Write-Host "  powershell -ExecutionPolicy Bypass -File .\install_sp_api_reprice_tasks.ps1 -MaxPatch 1"
    Write-Host "Then raise -MaxPatch or omit for full runs."
} elseif ($MaxPatch -gt 0) {
    Write-Host "Live PATCH capped at MaxPatch=$MaxPatch"
} else {
    Write-Host "Live PATCH has no count cap. Each run updates every changed SKU in order."
}

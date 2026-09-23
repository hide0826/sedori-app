#Requires -Version 5.1
<#
.SYNOPSIS
  Watchdog for HIRIO route list web (port 8792).
  Restarts "python -m route_web" if nothing is listening.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\watch.ps1
  powershell -ExecutionPolicy Bypass -File .\watch.ps1 -Install
#>
param(
    [switch]$Install
)

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonCwd = Split-Path $ScriptDir -Parent
$Repo = Split-Path $PythonCwd -Parent
$Python = Join-Path $Repo ".venv\Scripts\python.exe"
$LogDir = Join-Path $ScriptDir "logs"
$Log = Join-Path $LogDir "route_web_watchdog.log"
$TaskName = "HIRIO_route_web"
$Port = 8792

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

function Test-PortListening {
    $hit = netstat -ano | Select-String ":$Port " | Select-String "LISTENING"
    return [bool]$hit
}

function Get-WatchProcesses {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine -like "*route_web*watch.ps1*" -and
            $_.CommandLine -notlike "*-Install*"
        }
}

function Get-AppProcesses {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine -like "*-m route_web*"
        }
}

function Stop-PidTree([int]$ProcessId) {
    if ($ProcessId -le 0) { return }
    Write-WatchLog "stop PID=$ProcessId (tree)"
    & taskkill.exe /PID $ProcessId /T /F 2>$null | Out-Null
}

function Install-WatchTask {
    $script = Join-Path $ScriptDir "watch.ps1"
    $ps = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $action = New-ScheduledTaskAction `
        -Execute $ps `
        -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`"" `
        -WorkingDirectory $ScriptDir
    $triggerLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $triggerStartup = New-ScheduledTaskTrigger -AtStartup
    $triggerStartup.Delay = "PT2M"
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
    Write-Host "URL: http://houseserver:$Port/"
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

if (-not (Test-Path $Python)) {
    Write-WatchLog "python missing: $Python"
    exit 1
}

Write-WatchLog "watchdog start port=$Port"
while ($true) {
    if (-not (Test-PortListening)) {
        Write-WatchLog "port $Port not listening -> start route_web"
        Get-AppProcesses | ForEach-Object { Stop-PidTree -ProcessId $_.ProcessId }
        Start-Sleep -Seconds 1
        try {
            Start-Process -FilePath $Python -ArgumentList "-u -m route_web" `
                -WorkingDirectory $PythonCwd -WindowStyle Hidden
        } catch {
            Write-WatchLog "start failed: $_"
        }
        Start-Sleep -Seconds 5
    }
    Start-Sleep -Seconds 15
}

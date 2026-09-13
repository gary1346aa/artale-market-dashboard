# Artale Market Tracker - Scheduled Prompt Daemon
param (
    [switch]$TestNow,
    [switch]$RunNow
)

$ErrorActionPreference = 'Continue'
$workDir = 'C:\Users\gary1\artale_market_tracker'
Set-Location $workDir
$logFile = "$workDir\scheduler_daemon.log"

$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'

Add-Type -AssemblyName System.Windows.Forms

function Write-Log([string]$msg) {
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    "[$ts] $msg" | Out-File $logFile -Append -Encoding utf8
    Write-Host "[$ts] $msg"
}

function Get-NextStandardTarget([datetime]$baseTime) {
    $todayMidnight = $baseTime.Date                 # 00:00 Today
    $todayNoon = $todayMidnight.AddHours(12)        # 12:00 Today
    $tomorrowMidnight = $todayMidnight.AddDays(1)   # 00:00 Tomorrow
    $tomorrowNoon = $todayNoon.AddDays(1)           # 12:00 Tomorrow

    $candidates = @($todayMidnight, $todayNoon, $tomorrowMidnight, $tomorrowNoon) | Where-Object { $_ -gt $baseTime } | Sort-Object
    return $candidates[0]
}

function Show-PromptDialog([string]$promptTimeStr) {
    $title = 'Artale Market Tracker - Scheduled Collection'
    $lines = @(
        '[Artale Market Tracker - Scheduled Update]',
        '',
        "It is now the scheduled collection time ($promptTimeStr).",
        'Please choose how you want to collect auction data:',
        '',
        '  [Yes]    Full Update (Both: Asks + Trades)  [~5-6 mins]',
        '           Updates K-Lines, Lowest Asks, and Spreads',
        '',
        '  [No]     Fast Update (Trades Only)          [~2.5 mins]',
        '           Fastest scan, updates K-Line candlestick charts only',
        '',
        '  [Cancel] Postpone 30 Minutes',
        '           (I am currently using the PC, ask again later)'
    )
    $text = $lines -join [Environment]::NewLine

    $res = [System.Windows.Forms.MessageBox]::Show(
        $text,
        $title,
        [System.Windows.Forms.MessageBoxButtons]::YesNoCancel,
        [System.Windows.Forms.MessageBoxIcon]::Question,
        [System.Windows.Forms.MessageBoxDefaultButton]::Button1,
        [System.Windows.Forms.MessageBoxOptions]::ServiceNotification
    )

    if ($res -eq [System.Windows.Forms.DialogResult]::Yes) {
        return 'both'
    } elseif ($res -eq [System.Windows.Forms.DialogResult]::No) {
        return 'trades'
    } else {
        return 'postpone'
    }
}

function Show-Toast([string]$msg) {
    $title = 'Artale Market Tracker'
    [System.Windows.Forms.MessageBox]::Show(
        $msg,
        $title,
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Information,
        [System.Windows.Forms.MessageBoxDefaultButton]::Button1,
        [System.Windows.Forms.MessageBoxOptions]::ServiceNotification
    ) | Out-Null
}

Write-Log '=========================================='
Write-Log 'Artale Market Tracker Daemon Started.'
Write-Log 'Scheduled Target Times: Daily at 12:00 PM (Noon) and 12:00 AM (Midnight)'
Write-Log '=========================================='

if ($TestNow) {
    $nextPrompt = Get-Date
    Write-Log '[TEST MODE] Triggering test prompt dialog immediately...'
} elseif ($RunNow) {
    $nextPrompt = (Get-Date).AddSeconds(-1)
} else {
    $nextPrompt = Get-NextStandardTarget (Get-Date)
    Write-Log "Next scheduled prompt: $($nextPrompt.ToString('yyyy-MM-dd HH:mm:ss'))"
}

while ($true) {
    $now = Get-Date

    if ($now -ge $nextPrompt) {
        $promptTimeStr = $now.ToString('HH:mm')
        Write-Log 'Prompt dialog opened. Waiting for user choice...'

        $choice = Show-PromptDialog $promptTimeStr

        if ($choice -in @('both', 'trades')) {
            Write-Log "User selected mode: [$choice]. Launching run_auto.ps1 in visible terminal..."
            try {
                Start-Process powershell.exe -ArgumentList "-ExecutionPolicy Bypass -File `"$workDir\run_auto.ps1`" -TargetTab $choice" -Wait
                Write-Log "Collection ($choice) and GitHub Pages sync completed successfully!"
                Show-Toast "Market collection ($choice) and GitHub Pages sync completed successfully!"
            } catch {
                Write-Log "Error executing run_auto.ps1: $_"
                Show-Toast "Collection process encountered an error. Check log: $logFile"
            }

            # Recalculate next standard target (12:00 or 00:00)
            $nextPrompt = Get-NextStandardTarget (Get-Date)
            Write-Log "Schedule reset. Next scheduled prompt: $($nextPrompt.ToString('yyyy-MM-dd HH:mm:ss'))"

        } else {
            # User clicked [Cancel] or closed dialog
            $nextPrompt = (Get-Date).AddMinutes(30)
            $nextStr = $nextPrompt.ToString('HH:mm')
            Write-Log "User chose to postpone. Next prompt at: $($nextPrompt.ToString('yyyy-MM-dd HH:mm:ss'))"
            Show-Toast "Collection postponed.`nYou will be prompted again in 30 minutes (at $nextStr)."
        }
    }

    Start-Sleep -Seconds 15
}

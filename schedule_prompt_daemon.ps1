# Artale Market Tracker - 定時提醒與自動採集排程守護程式
param (
    [switch]$TestNow,
    [switch]$RunNow
)

$ErrorActionPreference = 'Continue'
$workDir = 'C:\Users\gary1\artale_market_tracker'
Set-Location $workDir
$logFile = "$workDir\scheduler_daemon.log"

Add-Type -AssemblyName System.Windows.Forms

function Write-Log([string]$msg) {
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    "[$ts] $msg" | Out-File $logFile -Append -Encoding utf8
    Write-Host "[$ts] $msg"
}

function Get-NextStandardTarget([datetime]$baseTime) {
    $todayMidnight = $baseTime.Date                 # 00:00 今日
    $todayNoon = $todayMidnight.AddHours(12)        # 12:00 今日
    $tomorrowMidnight = $todayMidnight.AddDays(1)   # 00:00 明日
    $tomorrowNoon = $todayNoon.AddDays(1)           # 12:00 明日

    $candidates = @($todayMidnight, $todayNoon, $tomorrowMidnight, $tomorrowNoon) | Where-Object { $_ -gt $baseTime } | Sort-Object
    return $candidates[0]
}

function Show-Prompt([string]$promptTimeStr) {
    $title = 'Artale Market Tracker - Market Collection'
    $lines = @(
        '[Artale Market Update / 行情定時採集]',
        '',
        "現在是預定的市場行情採集時間 ($promptTimeStr)。",
        '是否允許開始執行拍賣場自動掃描？',
        '(採集期間會自動切換與操作遊戲視窗約 2~3 分鐘)',
        '',
        '[是 (Yes)]  立即開始採集並同步至線上網站',
        '[否 (No)]   我正在使用電腦 (延後 30 分鐘後再次提醒)'
    )
    $text = $lines -join [Environment]::NewLine

    return [System.Windows.Forms.MessageBox]::Show(
        $text,
        $title,
        [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Question,
        [System.Windows.Forms.MessageBoxDefaultButton]::Button1,
        [System.Windows.Forms.MessageBoxOptions]::ServiceNotification
    )
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
Write-Log 'Artale 定時採集守護程式已啟動。'
Write-Log '固定排程目標時間：每日 12:00 PM (中午) 及 12:00 AM (午夜)'
Write-Log '=========================================='

if ($TestNow) {
    $nextPrompt = Get-Date
    Write-Log '[測試模式] 立即觸發詢問視窗...'
} elseif ($RunNow) {
    $nextPrompt = (Get-Date).AddSeconds(-1)
} else {
    $nextPrompt = Get-NextStandardTarget (Get-Date)
    Write-Log "下次詢問時間：$($nextPrompt.ToString('yyyy-MM-dd HH:mm:ss'))"
}

while ($true) {
    $now = Get-Date

    if ($now -ge $nextPrompt) {
        $promptTimeStr = $now.ToString('HH:mm')
        Write-Log '跳出詢問視窗 (等待使用者回應)...'

        $res = Show-Prompt $promptTimeStr

        if ($res -eq [System.Windows.Forms.DialogResult]::Yes) {
            Write-Log '使用者點選 [是]！正在啟動 run_auto.ps1 執行拍賣場採集與同步...'
            try {
                & powershell.exe -ExecutionPolicy Bypass -File "$workDir\run_auto.ps1"
                Write-Log '採集與 GitHub Pages 同步流程執行完畢！'
                Show-Toast '拍賣場行情採集與 GitHub Pages 同步已順利完成！'
            } catch {
                Write-Log "執行 run_auto.ps1 時發生異常: $_"
                Show-Toast "採集執行過程發生錯誤，請查看日誌：$logFile"
            }

            # 重新計算下一個固定目標時間 (12:00 或 00:00)
            $nextPrompt = Get-NextStandardTarget (Get-Date)
            Write-Log "排程已重設。下次詢問時間：$($nextPrompt.ToString('yyyy-MM-dd HH:mm:ss'))"

        } else {
            # 使用者點選 [否]
            $nextPrompt = (Get-Date).AddMinutes(30)
            $nextStr = $nextPrompt.ToString('HH:mm')
            Write-Log "使用者選擇延後。已延後 30 分鐘，下次詢問時間：$($nextPrompt.ToString('yyyy-MM-dd HH:mm:ss'))"
            Show-Toast "已為您延後採集排程。`n系統將在 30 分鐘後 ($nextStr) 再次詢問您。"
        }
    }

    Start-Sleep -Seconds 15
}

<#
.SYNOPSIS
    Artale Market Tracker - 定時提醒與自動採集排程守護程式
.DESCRIPTION
    每天固定於 12:00 PM (中午) 與 12:00 AM (午夜) 跳出系統最上層視窗詢問使用者是否可執行採集。
    - 點選 [是 (Yes)]：立即呼叫 run_auto.ps1 執行拍賣場掃描、K線聚合與 GitHub Pages 同步。
    - 點選 [否 (No)]：代表使用者正在操作電腦，自動延後 30 分鐘再次跳窗詢問。
#>

param (
    [switch]$TestNow,    # 立即觸發測試詢問視窗
    [switch]$RunNow      # 立即執行一次採集並進入排程
)

$ErrorActionPreference = "Continue"
$workDir = "C:\Users\gary1\artale_market_tracker"
Set-Location $workDir
$logFile = "$workDir\scheduler_daemon.log"

function Write-Log([string]$msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
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

$wshell = New-Object -ComObject Wscript.Shell
$daemonTitle = "🍁 Artale Market Tracker"

Write-Log "=========================================="
Write-Log "Artale 定時採集守護程式已啟動。"
Write-Log "固定排程目標時間：每日 12:00 PM (中午) 及 12:00 AM (午夜)"
Write-Log "=========================================="

if ($TestNow) {
    $nextPrompt = Get-Date
    Write-Log "啟用 -TestNow 模式：立即觸發詢問視窗..."
} elseif ($RunNow) {
    $nextPrompt = (Get-Date).AddSeconds(-1)
} else {
    $nextPrompt = Get-NextStandardTarget (Get-Date)
    Write-Log "下次詢問時間：$($nextPrompt.ToString('yyyy-MM-dd HH:mm:ss'))"
}

while ($true) {
    $now = Get-Date

    if ($now -ge $nextPrompt) {
        $promptTimeStr = $now.ToString("HH:mm")
        $msg = "【Artale 市場行情定時更新】`n`n現在是預定的市場數據採集時間 ($promptTimeStr)。`n`n是否允許開始執行拍賣場自動掃描？`n（採集期間會自動操作遊戲視窗約 2~3 分鐘）`n`n[是 (Y)]  立即開始採集並同步至線上網站`n[否 (N)]  我正在使用電腦（30 分鐘後再次提醒）"
        
        # 4 = Yes/No buttons, 32 = Question icon, 4096 = System Modal (always on top)
        Write-Log "跳出詢問視窗（等待使用者回應）..."
        $choice = $wshell.Popup($msg, 0, $daemonTitle, 4 + 32 + 4096)

        if ($choice -eq 6) {
            # 使用者點擊 [是]
            Write-Log "使用者同意執行！正在啟動 run_auto.ps1 執行拍賣場採集與同步..."
            
            # 呼叫自動採集腳本
            try {
                & powershell -ExecutionPolicy Bypass -File "$workDir\run_auto.ps1"
                Write-Log "採集與 GitHub Pages 同步流程執行完畢！"
                $wshell.Popup("✅ 拍賣場行情採集與 GitHub Pages 同步已順利完成！", 5, $daemonTitle, 64 + 4096) | Out-Null
            } catch {
                Write-Log "執行 run_auto.ps1 時發生異常: $_"
                $wshell.Popup("❌ 採集執行過程發生錯誤，請查看日誌：$logFile", 8, $daemonTitle, 16 + 4096) | Out-Null
            }

            # 重新計算下一個固定目標時間 (12:00 或 00:00)
            $nextPrompt = Get-NextStandardTarget (Get-Date)
            Write-Log "排程已重設。下次詢問時間：$($nextPrompt.ToString('yyyy-MM-dd HH:mm:ss'))"

        } else {
            # 使用者點擊 [否] 或關閉視窗
            $nextPrompt = (Get-Date).AddMinutes(30)
            Write-Log "使用者選擇延後（正在使用電腦）。已延後 30 分鐘，下次詢問時間：$($nextPrompt.ToString('yyyy-MM-dd HH:mm:ss'))"
            $wshell.Popup("⏳ 已為您延後採集排程。`n系統將在 30 分鐘後 ($($nextPrompt.ToString('HH:mm'))) 再次詢問您。", 4, $daemonTitle, 64 + 4096) | Out-Null
        }
    }

    # 每 15 秒檢查一次
    Start-Sleep -Seconds 15
}

# Artale Market Tracker - Scheduled Prompt Daemon
param (
    [switch]$TestNow,
    [switch]$RunNow,
    [int]$TimeoutSec = 30
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
    # Aligns to hourly scan schedule (every hour on the hour: 00:00, 01:00, 02:00, 03:00, ...)
    $startOfDay = $baseTime.Date
    $slots = @()
    for ($h = 0; $h -lt 48; $h += 1) {
        $slot = $startOfDay.AddHours($h)
        if ($slot -gt $baseTime) {
            $slots += $slot
        }
    }
    return $slots[0]
}

Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName PresentationCore
Add-Type -AssemblyName WindowsBase

function Show-PromptDialog([string]$promptTimeStr, [int]$timeout = 30) {
    # Dynamically read current watchlist and due item count
    $watchlistPath = "$workDir\items_watchlist.json"
    $pythonExe = "C:\Users\gary1\AppData\Local\Programs\Python\Python314\python.exe"
    $itemCount = 105
    $dueCount = 0

    if (Test-Path $watchlistPath) {
        try {
            $wl = Get-Content $watchlistPath -Raw -Encoding utf8 | ConvertFrom-Json
            if ($wl.PSObject.Properties) {
                $itemCount = @($wl.PSObject.Properties).Count
            } else {
                $itemCount = @($wl).Count
            }
        } catch {
            $itemCount = 105
        }
    }

    try {
        $cmd = "from core.watchlist import get_due_items; due, _, _ = get_due_items(); print(len(due))"
        $res = & $pythonExe -c $cmd
        $dueCount = [int]$res.Trim()
    } catch {
        $dueCount = 18
    }

    $script:isAutoTriggered = $false
    $timeoutSec = $timeout

    try {
        [xml]$xaml = @"
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Artale Market Tracker - Scheduled Collection"
        Height="450" Width="550"
        WindowStartupLocation="CenterScreen"
        Topmost="True" ResizeMode="NoResize"
        Background="#F3F4F6" FontFamily="Segoe UI">
    <Grid Margin="20">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
        </Grid.RowDefinitions>

        <StackPanel Grid.Row="0">
            <TextBlock Text="Artale Market Tracker - Scheduled Update" FontSize="16" FontWeight="Bold" Foreground="#111827"/>
            <TextBlock Text="Scheduled time ($promptTimeStr) reached. Due for collection: $dueCount items (out of $itemCount total)." FontSize="12" Foreground="#4B5563" Margin="0,2,0,0"/>
            <TextBlock Text="Please choose an option (or press A / B / C / D):" FontSize="13" Foreground="#1F2937" Margin="0,6,0,0"/>
        </StackPanel>

        <!-- Unattended Auto-Proceed Banner -->
        <Border Grid.Row="1" Background="#FEF3C7" BorderBrush="#F59E0B" BorderThickness="1" CornerRadius="6" Padding="10,8" Margin="0,8,0,10">
            <StackPanel Orientation="Horizontal" VerticalAlignment="Center">
                <TextBlock Text="&#x23F1; " FontSize="14"/>
                <TextBlock Name="TxtCountdown" Text="Auto-proceeding with Both [C] in 30s if unattended... (Press D to Cancel)" FontWeight="SemiBold" FontSize="12" Foreground="#92400E"/>
            </StackPanel>
        </Border>

        <StackPanel Grid.Row="2">
            <!-- Button A: Ask -->
            <Button Name="BtnA" Height="48" Margin="0,0,0,8" Background="#2563EB" Foreground="White" BorderThickness="0" Cursor="Hand">
                <StackPanel Margin="12,4,12,4">
                    <TextBlock Text="[A]  Ask Only (Active Listings - Due Items)" FontWeight="Bold" FontSize="13"/>
                    <TextBlock Text="Scans active listings for $dueCount due items. Updates Lowest Asks &amp; Spreads." FontSize="11" Opacity="0.9"/>
                </StackPanel>
            </Button>

            <!-- Button B: Trade -->
            <Button Name="BtnB" Height="48" Margin="0,0,0,8" Background="#059669" Foreground="White" BorderThickness="0" Cursor="Hand">
                <StackPanel Margin="12,4,12,4">
                    <TextBlock Text="[B]  Trade Only (Matched Trades - Due Items)" FontWeight="Bold" FontSize="13"/>
                    <TextBlock Text="Scans matched trades for $dueCount due items. Updates K-Line charts." FontSize="11" Opacity="0.9"/>
                </StackPanel>
            </Button>

            <!-- Button C: Both (Auto-Default) -->
            <Button Name="BtnC" Height="52" Margin="0,0,0,8" Background="#7C3AED" Foreground="White" BorderThickness="0" Cursor="Hand">
                <StackPanel Margin="12,5,12,5">
                    <StackPanel Orientation="Horizontal">
                        <TextBlock Text="[C]  Both (Ask + Trade - Due Items)" FontWeight="Bold" FontSize="13"/>
                        <Border Background="#A78BFA" CornerRadius="4" Padding="6,1" Margin="8,0,0,0">
                            <TextBlock Text="Auto-Default" FontSize="10" FontWeight="Bold" Foreground="White"/>
                        </Border>
                    </StackPanel>
                    <TextBlock Text="Full scan for $dueCount due items. Re-evaluates tiers and syncs dashboard." FontSize="11" Opacity="0.9"/>
                </StackPanel>
            </Button>

            <!-- Button D: Cancel / Postpone -->
            <Button Name="BtnD" Height="38" Background="#E5E7EB" Foreground="#1F2937" BorderThickness="1" BorderBrush="#D1D5DB" Cursor="Hand">
                <TextBlock Text="[D]  Postpone (Ask Again in 30 Mins)" FontWeight="SemiBold" FontSize="12"/>
            </Button>
        </StackPanel>
    </Grid>
</Window>
"@
        $reader = (New-Object System.Xml.XmlNodeReader $xaml)
        $window = [System.Windows.Markup.XamlReader]::Load($reader)

        $script:dialogChoice = "both"
        $script:countdown = $timeoutSec

        $btnA = $window.FindName("BtnA")
        $btnB = $window.FindName("BtnB")
        $btnC = $window.FindName("BtnC")
        $btnD = $window.FindName("BtnD")
        $txtCountdown = $window.FindName("TxtCountdown")

        # DispatcherTimer for 30s auto-proceed when unattended
        $timer = New-Object System.Windows.Threading.DispatcherTimer
        $timer.Interval = [TimeSpan]::FromSeconds(1)
        $timer.Add_Tick({
            $script:countdown--
            if ($null -ne $txtCountdown) {
                $txtCountdown.Text = "Auto-proceeding with Both [C] in $($script:countdown)s if unattended... (Press D to Cancel)"
            }
            if ($script:countdown -le 0) {
                $timer.Stop()
                $script:isAutoTriggered = $true
                $script:dialogChoice = "both"
                $window.Close()
            }
        })

        $btnA.Add_Click({
            $timer.Stop()
            $script:dialogChoice = "asks"
            $window.Close()
        })

        $btnB.Add_Click({
            $timer.Stop()
            $script:dialogChoice = "trades"
            $window.Close()
        })

        $btnC.Add_Click({
            $timer.Stop()
            $script:dialogChoice = "both"
            $window.Close()
        })

        $btnD.Add_Click({
            $timer.Stop()
            $script:dialogChoice = "postpone"
            $window.Close()
        })

        $window.Add_KeyDown({
            param($sender, $e)
            if ($e.Key -eq [System.Windows.Input.Key]::A) {
                $timer.Stop()
                $script:dialogChoice = "asks"
                $window.Close()
            } elseif ($e.Key -eq [System.Windows.Input.Key]::B) {
                $timer.Stop()
                $script:dialogChoice = "trades"
                $window.Close()
            } elseif ($e.Key -eq [System.Windows.Input.Key]::C) {
                $timer.Stop()
                $script:dialogChoice = "both"
                $window.Close()
            } elseif ($e.Key -eq [System.Windows.Input.Key]::Escape -or $e.Key -eq [System.Windows.Input.Key]::D) {
                $timer.Stop()
                $script:dialogChoice = "postpone"
                $window.Close()
            }
        })

        $window.Add_Loaded({
            $timer.Start()
        })

        $window.Add_Closed({
            $timer.Stop()
        })

        $null = $window.ShowDialog()
        return $script:dialogChoice
    } catch {
        # Fallback to Wscript.Shell Popup with 30s auto-dismiss
        Write-Log "WPF Dialog failed: $_. Using 30s timed fallback popup..."
        $title = 'Artale Market Tracker - Scheduled Collection'
        $msg = "Scheduled collection time ($promptTimeStr) reached.`nDue items: $dueCount.`n`nClick OK to start collection (Both tabs), or Cancel to postpone 30 mins.`n`n(Auto-proceeds in 30 seconds if unattended...)"
        try {
            $wshell = New-Object -ComObject Wscript.Shell
            # Popup buttons: 1 = OK/Cancel, Icon: 32 = Question
            $res = $wshell.Popup($msg, $timeoutSec, $title, 1 + 32)
            if ($res -eq 2) { return 'postpone' }
            if ($res -eq -1) { $script:isAutoTriggered = $true }
            return 'both'
        } catch {
            $script:isAutoTriggered = $true
            return 'both'
        }
    }
}

function Show-Toast([string]$msg) {
    try {
        $wshell = New-Object -ComObject Wscript.Shell
        # Auto-dismiss after 6 seconds so the daemon never hangs
        $wshell.Popup($msg, 6, "Artale Market Tracker", 64) | Out-Null
    } catch {
        Write-Log "Toast notification error: $_"
    }
}

Write-Log 'Artale Market Tracker Daemon Started.'

# Set system to Balanced power scheme during daemon idle
try { powercfg /setactive 381b4222-f694-41f0-9685-ff5bb260df2e } catch {}

# Run immediately once upon startup, then follow standard hourly schedule
$nextPrompt = (Get-Date).AddSeconds(-1)

function Get-DueStatus() {
    $pyCmd = "import sys; sys.stdout.reconfigure(encoding='utf-8'); import json; from core.watchlist import get_due_items; due, wait_sec, next_item = get_due_items(); wl = json.load(open('items_watchlist.json', 'r', encoding='utf-8')); print(json.dumps({'due_count': len(due), 'total_count': len(wl), 'wait_min': round(wait_sec/60, 1), 'next_item': next_item, 'due_items': due}, ensure_ascii=False))"
    try {
        $raw = & "C:\Users\gary1\AppData\Local\Programs\Python\Python314\python.exe" -c $pyCmd
        return ($raw | ConvertFrom-Json)
    } catch {
        return $null
    }
}

while ($true) {
    $now = Get-Date

    if ($now -ge $nextPrompt) {
        $dueInfo = Get-DueStatus
        if ($null -ne $dueInfo) {
            $dueCount = $dueInfo.due_count
            $totalCount = $dueInfo.total_count
            $waitMin = $dueInfo.wait_min
            $nextItem = $dueInfo.next_item
            $dueList = @($dueInfo.due_items)

            if ($dueCount -eq 0) {
                Write-Log "Watchlist Check: 0 of $totalCount items due to update. All items up to date."
            } else {
                $sample = if ($dueList.Count -gt 6) { ($dueList[0..5] -join ', ') + " (+$(($dueList.Count - 6)) more)" } else { $dueList -join ', ' }
                Write-Log "Watchlist Check: $dueCount of $totalCount item(s) due to update: [$sample]"
                Write-Log "Starting collection for $dueCount due item(s)..."
                try {
                    & "$workDir\run_auto.ps1" -TargetTab both -Due -AutoPowerSave
                    if ($LASTEXITCODE -eq 0) {
                        Write-Log "Collection ($dueCount items) and sync completed."
                    } else {
                        Write-Log "Collection exited with code $LASTEXITCODE. Check collector_run.log for details."
                    }
                } catch {
                    Write-Log "Error executing run_auto.ps1: $_"
                }
            }
        } else {
            Write-Log "Scheduled target reached ($($now.ToString('HH:mm'))). Starting collection..."
            try {
                & "$workDir\run_auto.ps1" -TargetTab both -Due -AutoPowerSave
                if ($LASTEXITCODE -eq 0) {
                    Write-Log "Collection and sync completed."
                } else {
                    Write-Log "Collection exited with code $LASTEXITCODE. Check collector_run.log for details."
                }
            } catch {
                Write-Log "Error executing run_auto.ps1: $_"
            }
        }

        # Recalculate next standard target (hourly)
        $nextPrompt = Get-NextStandardTarget (Get-Date)
        Write-Log "Schedule reset. Next scheduled run at: $($nextPrompt.ToString('yyyy-MM-dd HH:mm:ss'))"
    }

    Start-Sleep -Seconds 15
}

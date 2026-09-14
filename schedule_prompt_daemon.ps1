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
    # Aligns to 2-hour scan schedule: 00:00, 02:00, 04:00, 06:00, 08:00, 10:00, 12:00, 14:00, 16:00, 18:00, 20:00, 22:00
    $startOfDay = $baseTime.Date
    $slots = @()
    for ($h = 0; $h -lt 48; $h += 2) {
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

function Show-PromptDialog([string]$promptTimeStr) {
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
        $cmd = "from src.tier_evaluator import get_due_items; due, _, _ = get_due_items(); print(len(due))"
        $res = & $pythonExe -c $cmd
        $dueCount = [int]$res.Trim()
    } catch {
        $dueCount = 18
    }

    try {
        [xml]$xaml = @"
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Artale Market Tracker - Scheduled Collection"
        Height="430" Width="540"
        WindowStartupLocation="CenterScreen"
        Topmost="True" ResizeMode="NoResize"
        Background="#F3F4F6" FontFamily="Segoe UI">
    <Grid Margin="20">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="12"/>
            <RowDefinition Height="*"/>
        </Grid.RowDefinitions>

        <StackPanel Grid.Row="0">
            <TextBlock Text="Artale Market Tracker - Scheduled Update" FontSize="16" FontWeight="Bold" Foreground="#111827"/>
            <TextBlock Text="Scheduled time ($promptTimeStr) reached. Due for collection: $dueCount items (out of $itemCount total)." FontSize="12" Foreground="#4B5563" Margin="0,2,0,0"/>
            <TextBlock Text="Please choose an option to proceed (or press A / B / C / D):" FontSize="13" Foreground="#1F2937" Margin="0,6,0,0"/>
        </StackPanel>

        <StackPanel Grid.Row="2">
            <!-- Button A: Ask -->
            <Button Name="BtnA" Height="50" Margin="0,0,0,8" Background="#2563EB" Foreground="White" BorderThickness="0" Cursor="Hand">
                <StackPanel Margin="12,5,12,5">
                    <TextBlock Text="[A]  Ask Only (Active Listings - Due Items)" FontWeight="Bold" FontSize="13"/>
                    <TextBlock Text="Scans active listings for $dueCount due items. Updates Lowest Asks &amp; Spreads." FontSize="11" Opacity="0.9"/>
                </StackPanel>
            </Button>

            <!-- Button B: Trade -->
            <Button Name="BtnB" Height="50" Margin="0,0,0,8" Background="#059669" Foreground="White" BorderThickness="0" Cursor="Hand">
                <StackPanel Margin="12,5,12,5">
                    <TextBlock Text="[B]  Trade Only (Matched Trades - Due Items)" FontWeight="Bold" FontSize="13"/>
                    <TextBlock Text="Scans matched trades for $dueCount due items. Updates K-Line charts." FontSize="11" Opacity="0.9"/>
                </StackPanel>
            </Button>

            <!-- Button C: Both -->
            <Button Name="BtnC" Height="50" Margin="0,0,0,8" Background="#7C3AED" Foreground="White" BorderThickness="0" Cursor="Hand">
                <StackPanel Margin="12,5,12,5">
                    <TextBlock Text="[C]  Both (Ask + Trade - Due Items)" FontWeight="Bold" FontSize="13"/>
                    <TextBlock Text="Scans both tabs for $dueCount due items. Re-evaluates tiers and syncs dashboard." FontSize="11" Opacity="0.9"/>
                </StackPanel>
            </Button>

            <!-- Button B: Trade -->
            <Button Name="BtnB" Height="50" Margin="0,0,0,8" Background="#059669" Foreground="White" BorderThickness="0" Cursor="Hand">
                <StackPanel Margin="12,5,12,5">
                    <TextBlock Text="[B]  Trade Only (Matched Trades)" FontWeight="Bold" FontSize="13"/>
                    <TextBlock Text="Scans matched trades only. Updates K-Line candlestick charts." FontSize="11" Opacity="0.9"/>
                </StackPanel>
            </Button>

            <!-- Button C: Both -->
            <Button Name="BtnC" Height="50" Margin="0,0,0,8" Background="#7C3AED" Foreground="White" BorderThickness="0" Cursor="Hand">
                <StackPanel Margin="12,5,12,5">
                    <TextBlock Text="[C]  Both (Ask + Trade)" FontWeight="Bold" FontSize="13"/>
                    <TextBlock Text="Full update: scans both tabs. Updates K-Lines, Lowest Asks, and Spreads." FontSize="11" Opacity="0.9"/>
                </StackPanel>
            </Button>

            <!-- Button D: Cancel -->
            <Button Name="BtnD" Height="38" Background="#E5E7EB" Foreground="#1F2937" BorderThickness="1" BorderBrush="#D1D5DB" Cursor="Hand">
                <TextBlock Text="[D]  Cancel (Ask Again in 30 Mins)   [I am currently using the PC]" FontWeight="SemiBold" FontSize="12"/>
            </Button>
        </StackPanel>
    </Grid>
</Window>
"@
        $reader = (New-Object System.Xml.XmlNodeReader $xaml)
        $window = [System.Windows.Markup.XamlReader]::Load($reader)

        $script:dialogChoice = "postpone"

        $btnA = $window.FindName("BtnA")
        $btnB = $window.FindName("BtnB")
        $btnC = $window.FindName("BtnC")
        $btnD = $window.FindName("BtnD")

        $btnA.Add_Click({
            $script:dialogChoice = "asks"
            $window.Close()
        })

        $btnB.Add_Click({
            $script:dialogChoice = "trades"
            $window.Close()
        })

        $btnC.Add_Click({
            $script:dialogChoice = "both"
            $window.Close()
        })

        $btnD.Add_Click({
            $script:dialogChoice = "postpone"
            $window.Close()
        })

        $window.Add_KeyDown({
            param($sender, $e)
            if ($e.Key -eq [System.Windows.Input.Key]::A) {
                $script:dialogChoice = "asks"
                $window.Close()
            } elseif ($e.Key -eq [System.Windows.Input.Key]::B) {
                $script:dialogChoice = "trades"
                $window.Close()
            } elseif ($e.Key -eq [System.Windows.Input.Key]::C) {
                $script:dialogChoice = "both"
                $window.Close()
            } elseif ($e.Key -eq [System.Windows.Input.Key]::Escape -or $e.Key -eq [System.Windows.Input.Key]::D) {
                $script:dialogChoice = "postpone"
                $window.Close()
            }
        })

        $null = $window.ShowDialog()
        return $script:dialogChoice
    } catch {
        # Fallback to MessageBox if WPF fails
        $title = 'Artale Market Tracker - Scheduled Collection'
        $lines = @(
            '[Artale Market Tracker - Scheduled Update]',
            '',
            "It is now the scheduled collection time ($promptTimeStr).",
            "Target watchlist: $itemCount items. Please choose an option:",
            '',
            '  [Yes]    [C] Both (Ask + Trade)',
            '           Updates K-Lines, Lowest Asks, and Spreads',
            '',
            '  [No]     [B] Trade Only (Matched Trades)',
            '           Updates K-Line candlestick charts only',
            '',
            '  [Cancel] [D] Postpone 30 Minutes',
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

        if ($res -eq [System.Windows.Forms.DialogResult]::Yes) { return 'both' }
        elseif ($res -eq [System.Windows.Forms.DialogResult]::No) { return 'trades' }
        else { return 'postpone' }
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

Write-Log '=========================================='
Write-Log 'Artale Market Tracker Daemon Started.'
Write-Log 'Scheduled Target Times: Every 2 Hours (00:00, 02:00, 04:00, 06:00, 08:00, 10:00, 12:00, 14:00, 16:00, 18:00, 20:00, 22:00)'
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

        if ($choice -in @('both', 'trades', 'asks')) {
            Write-Log "User selected mode: [$choice]. Launching run_auto.ps1 for due items..."
            try {
                Start-Process powershell.exe -ArgumentList "-ExecutionPolicy Bypass -File `"$workDir\run_auto.ps1`" -TargetTab $choice -Due" -Wait
                Write-Log "Collection ($choice) and GitHub Pages sync completed successfully!"
            } catch {
                Write-Log "Error executing run_auto.ps1: $_"
                Show-Toast "Collection process encountered an error. Check log: $logFile"
            }

            # Recalculate next standard target (every 2 hours)
            $nextPrompt = Get-NextStandardTarget (Get-Date)
            Write-Log "Schedule reset. Next scheduled prompt: $($nextPrompt.ToString('yyyy-MM-dd HH:mm:ss'))"
            Show-Toast "Market collection ($choice) completed successfully!`nNext scheduled scan at: $($nextPrompt.ToString('HH:mm'))."

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

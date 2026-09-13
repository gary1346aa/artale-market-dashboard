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

Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName PresentationCore
Add-Type -AssemblyName WindowsBase

function Show-PromptDialog([string]$promptTimeStr) {
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
            <TextBlock Text="Scheduled time ($promptTimeStr) reached. Target watchlist: 84 items." FontSize="12" Foreground="#4B5563" Margin="0,2,0,0"/>
            <TextBlock Text="Please choose an option to proceed (or press A / B / C / D):" FontSize="13" Foreground="#1F2937" Margin="0,6,0,0"/>
        </StackPanel>

        <StackPanel Grid.Row="2">
            <!-- Button A: Ask -->
            <Button Name="BtnA" Height="50" Margin="0,0,0,8" Background="#2563EB" Foreground="White" BorderThickness="0" Cursor="Hand">
                <StackPanel Margin="12,5,12,5">
                    <TextBlock Text="[A]  Ask Only (Active Listings)      [ETA: ~10-12 mins]" FontWeight="Bold" FontSize="13"/>
                    <TextBlock Text="Scans active listings only. Updates Lowest Asks &amp; Spreads." FontSize="11" Opacity="0.9"/>
                </StackPanel>
            </Button>

            <!-- Button B: Trade -->
            <Button Name="BtnB" Height="50" Margin="0,0,0,8" Background="#059669" Foreground="White" BorderThickness="0" Cursor="Hand">
                <StackPanel Margin="12,5,12,5">
                    <TextBlock Text="[B]  Trade Only (Matched Trades)     [ETA: ~10-12 mins]" FontWeight="Bold" FontSize="13"/>
                    <TextBlock Text="Scans matched trades only. Updates K-Line candlestick charts." FontSize="11" Opacity="0.9"/>
                </StackPanel>
            </Button>

            <!-- Button C: Both -->
            <Button Name="BtnC" Height="50" Margin="0,0,0,8" Background="#7C3AED" Foreground="White" BorderThickness="0" Cursor="Hand">
                <StackPanel Margin="12,5,12,5">
                    <TextBlock Text="[C]  Both (Ask + Trade)              [ETA: ~20-25 mins]" FontWeight="Bold" FontSize="13"/>
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
            'Target watchlist: 84 items. Please choose an option:',
            '',
            '  [Yes]    [C] Both (Ask + Trade)          [~20-25 mins]',
            '           Updates K-Lines, Lowest Asks, and Spreads',
            '',
            '  [No]     [B] Trade Only (Matched Trades) [~10-12 mins]',
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

        if ($choice -in @('both', 'trades', 'asks')) {
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

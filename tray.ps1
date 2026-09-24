[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Launcher = Join-Path $Root 'launch.ps1'
$IconPath = Join-Path $Root 'src\local_meeting_ai\web\static\icons\solvit.ico'
$PowerShell = (Get-Command powershell.exe).Source
$Created = $false
$Mutex = New-Object System.Threading.Mutex($true, 'Local\MeetingBySolvitTray', [ref]$Created)
if (-not $Created) {
    $Mutex.Dispose()
    return
}

try {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing

    # Starting the tray never starts a recording or opens a browser window.
    & $Launcher -ServerOnly

    $Icon = New-Object System.Drawing.Icon($IconPath)
    $Menu = New-Object System.Windows.Forms.ContextMenuStrip
    $OpenItem = $Menu.Items.Add('Abrir Meeting by Solvit')
    $StopItem = $Menu.Items.Add('Desligar aplicativo e sair')
    $Context = New-Object System.Windows.Forms.ApplicationContext
    $Tray = New-Object System.Windows.Forms.NotifyIcon
    $Tray.Icon = $Icon
    $Tray.Text = 'Meeting by Solvit'
    $Tray.ContextMenuStrip = $Menu
    $Tray.Visible = $true

    $OpenMeeting = {
        $Arguments = '-NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Hidden -File "' + $Launcher + '"'
        Start-Process -FilePath $PowerShell -ArgumentList $Arguments -WindowStyle Hidden | Out-Null
    }
    $OpenItem.add_Click($OpenMeeting)
    $Tray.add_DoubleClick($OpenMeeting)
    $StopItem.add_Click({
        try {
            $ActiveCapture = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/capture/session' -TimeoutSec 5
            if ($null -ne $ActiveCapture) {
                [System.Windows.Forms.MessageBox]::Show(
                    'Há uma gravação ativa. Pare a reunião no aplicativo antes de desligar.',
                    'Meeting by Solvit'
                ) | Out-Null
                return
            }
            Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8765/api/application/shutdown' -TimeoutSec 5 | Out-Null
        } catch {
            # The server may already have been stopped from the interface.
        }
        $Tray.Visible = $false
        $Context.ExitThread()
    })

    [System.Windows.Forms.Application]::Run($Context)
} finally {
    if ($null -ne $Tray) { $Tray.Visible = $false; $Tray.Dispose() }
    if ($null -ne $Menu) { $Menu.Dispose() }
    if ($null -ne $Icon) { $Icon.Dispose() }
    $Mutex.ReleaseMutex()
    $Mutex.Dispose()
}

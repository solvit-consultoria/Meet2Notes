[CmdletBinding()]
param([switch]$NoStart)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$TrayScript = Join-Path $Root 'tray.ps1'
$Startup = [Environment]::GetFolderPath('Startup')
$ShortcutPath = Join-Path $Startup 'Meeting by Solvit.lnk'
$PowerShell = (Get-Command powershell.exe).Source
$Arguments = '-NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Hidden -File "' + $TrayScript + '"'

if (-not (Test-Path -LiteralPath (Join-Path $Root '.venv\Scripts\python.exe'))) {
    throw 'Meeting by Solvit não está instalado. Execute .\install.ps1 -Mvp primeiro.'
}

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $PowerShell
$Shortcut.Arguments = $Arguments
$Shortcut.WorkingDirectory = $Root
$Shortcut.Description = 'Iniciar Meeting by Solvit na bandeja ao entrar no Windows'
$Shortcut.IconLocation = Join-Path $Root 'src\local_meeting_ai\web\static\icons\solvit.ico'
$Shortcut.Save()
Write-Host "Início com Windows ativado: $ShortcutPath"

if (-not $NoStart) {
    Start-Process -FilePath $PowerShell -ArgumentList $Arguments -WindowStyle Hidden | Out-Null
    Write-Host 'Ícone solicitado na bandeja. Use a seta de ícones ocultos, se necessário.'
}

[CmdletBinding()]
param([switch]$NoStart)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$TrayScript = Join-Path $Root 'tray.ps1'
$HiddenLauncher = Join-Path $Root 'tray-hidden.vbs'
$Startup = [Environment]::GetFolderPath('Startup')
$ShortcutPath = Join-Path $Startup 'Meeting by Solvit.lnk'
$PowerShell = (Get-Command powershell.exe).Source
$Arguments = '-NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Hidden -File "' + $TrayScript + '"'

if (-not (Test-Path -LiteralPath (Join-Path $Root '.venv\Scripts\python.exe'))) {
    throw 'Meeting by Solvit não está instalado. Execute .\install.ps1 -Mvp primeiro.'
}

# A shortcut's own window style can override PowerShell's -WindowStyle Hidden
# during Windows logon. Let Windows Script Host launch it without a console.
$Vbs = @'
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = "@@ROOT@@"
shell.Run "@@POWERSHELL@@ @@ARGUMENTS@@", 0, False
'@
$Vbs = $Vbs.Replace('@@ROOT@@', $Root.Replace('"', '""'))
$Vbs = $Vbs.Replace('@@POWERSHELL@@', $PowerShell.Replace('"', '""'))
$Vbs = $Vbs.Replace('@@ARGUMENTS@@', $Arguments.Replace('"', '""'))
Set-Content -LiteralPath $HiddenLauncher -Value $Vbs -Encoding ASCII

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = Join-Path $env:WINDIR 'System32\wscript.exe'
$Shortcut.Arguments = '//B //Nologo "' + $HiddenLauncher + '"'
$Shortcut.WorkingDirectory = $Root
$Shortcut.WindowStyle = 7
$Shortcut.Description = 'Iniciar Meeting by Solvit na bandeja ao entrar no Windows'
$Shortcut.IconLocation = Join-Path $Root 'src\local_meeting_ai\web\static\icons\solvit.ico'
$Shortcut.Save()
Write-Host "Início com Windows ativado: $ShortcutPath"

if (-not $NoStart) {
    Start-Process -FilePath $PowerShell -ArgumentList $Arguments -WindowStyle Hidden | Out-Null
    Write-Host 'Ícone solicitado na bandeja. Use a seta de ícones ocultos, se necessário.'
}

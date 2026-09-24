[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Launcher = Join-Path $Root 'launch.ps1'
$Programs = [Environment]::GetFolderPath('Programs')
$ShortcutPath = Join-Path $Programs 'Meeting by Solvit.lnk'
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = (Get-Command powershell.exe).Source
$Shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $Launcher + '"'
$Shortcut.WorkingDirectory = $Root
$Shortcut.Description = 'Abrir Meeting by Solvit e iniciar o servidor local, se necessário'
$Shortcut.IconLocation = (Join-Path $Root 'src\local_meeting_ai\web\static\icons\solvit.ico')
$Shortcut.Save()
Write-Host "Atalho criado: $ShortcutPath"

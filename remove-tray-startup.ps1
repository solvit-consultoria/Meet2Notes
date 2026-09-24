[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ShortcutPath = Join-Path ([Environment]::GetFolderPath('Startup')) 'Meeting by Solvit.lnk'
if (Test-Path -LiteralPath $ShortcutPath) {
    Remove-Item -LiteralPath $ShortcutPath
    Write-Host 'Início automático removido. O ícone atual pode ser fechado pelo menu da bandeja.'
} else {
    Write-Host 'O início automático já estava desativado.'
}

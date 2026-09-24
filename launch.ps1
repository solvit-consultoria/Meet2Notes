[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$Url = 'http://127.0.0.1:8765/'

if (-not (Test-Path -LiteralPath $Python)) {
    throw 'Meeting by Solvit não está instalado. Execute .\install.ps1 -Mvp primeiro.'
}

function Test-MeetingReady {
    try {
        $Health = Invoke-RestMethod -Uri ($Url + 'api/health') -TimeoutSec 2
        return $Health.status -eq 'ok'
    } catch {
        return $false
    }
}

if (-not (Test-MeetingReady)) {
    Start-Process -FilePath $Python -ArgumentList '-m', 'local_meeting_ai', '--no-browser' `
        -WorkingDirectory $Root -WindowStyle Hidden | Out-Null
    $Ready = $false
    for ($Attempt = 0; $Attempt -lt 40; $Attempt++) {
        Start-Sleep -Milliseconds 500
        if (Test-MeetingReady) { $Ready = $true; break }
    }
    if (-not $Ready) { throw 'O servidor local não iniciou. Verifique os logs do aplicativo.' }
}

$Chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
if (-not (Test-Path -LiteralPath $Chrome)) {
    $Chrome = 'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe'
}
if (Test-Path -LiteralPath $Chrome) {
    Start-Process -FilePath $Chrome -ArgumentList ('--app=' + $Url)
} else {
    Start-Process $Url
}

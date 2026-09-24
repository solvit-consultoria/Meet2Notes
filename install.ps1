[CmdletBinding()]
param(
    [ValidateSet("auto", "cpu", "cuda")]
    [string]$AiBackend = "auto",

    [ValidateSet("all", "none")]
    [string]$Models = "all",

    [ValidateSet(
        "tiny",
        "base",
        "small",
        "medium",
        "large-v3",
        "distil-large-v3",
        "turbo"
    )]
    [string]$WhisperModel = "small",

    [string]$ModelsDirectory = "",

    [switch]$SkipFfmpeg,
    [switch]$SkipModels,
    [switch]$InstallDiarization,
    [switch]$Mvp,
    [switch]$Dev,
    [switch]$Start
)

$ErrorActionPreference = "Stop"
$InstallerRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvironmentRoot = Join-Path $InstallerRoot ".venv"
$EnvironmentPython = Join-Path $EnvironmentRoot "Scripts\python.exe"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Checked {
    param(
        [string]$Command,
        [string[]]$Arguments
    )
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $Command $($Arguments -join ' ')"
    }
}

function Get-BootstrapPython {
    $Launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($Launcher) {
        foreach ($Version in @("-3.12", "-3.13", "-3.11")) {
            & $Launcher.Source $Version -c "import sys; print(sys.executable)" *> $null
            if ($LASTEXITCODE -eq 0) {
                return @($Launcher.Source, $Version)
            }
        }
    }

    $Python = Get-Command python -ErrorAction SilentlyContinue
    if ($Python) {
        return @($Python.Source)
    }
    throw "Python 3.11+ was not found. Install it from https://www.python.org/downloads/"
}

function Add-DiscoveredFfmpegToPath {
    $Candidates = @()
    foreach ($Candidate in ([Environment]::GetEnvironmentVariable('Path', 'User') -split ';')) {
        if ($Candidate) { $Candidates += $Candidate }
    }
    $WingetLinks = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links'
    if (Test-Path -LiteralPath $WingetLinks) { $Candidates += $WingetLinks }

    $PackageRoots = @(
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'),
        (Join-Path $env:ProgramFiles 'WinGet\Packages')
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    foreach ($PackageRoot in $PackageRoots) {
        foreach ($Package in (Get-ChildItem -LiteralPath $PackageRoot -Directory -Filter 'Gyan.FFmpeg*' -ErrorAction SilentlyContinue)) {
            foreach ($Executable in (Get-ChildItem -LiteralPath $Package.FullName -Filter 'ffmpeg.exe' -File -Recurse -ErrorAction SilentlyContinue)) {
                $Candidates += $Executable.DirectoryName
            }
        }
    }

    foreach ($Candidate in ($Candidates | Select-Object -Unique)) {
        if ((Test-Path -LiteralPath (Join-Path $Candidate 'ffmpeg.exe')) -and
            (Test-Path -LiteralPath (Join-Path $Candidate 'ffprobe.exe'))) {
            if (-not (($env:PATH -split ';') -contains $Candidate)) {
                $env:PATH = "$Candidate;$env:PATH"
            }
            return $true
        }
    }
    return [bool]((Get-Command ffmpeg -ErrorAction SilentlyContinue) -and
        (Get-Command ffprobe -ErrorAction SilentlyContinue))
}

function Install-Ffmpeg {
    if (Add-DiscoveredFfmpegToPath) {
        Write-Host "FFmpeg and FFprobe are already available."
        return $true
    }
    if ($SkipFfmpeg) {
        Write-Warning "FFmpeg/FFprobe are missing. Media import and transcription are not ready."
        return $false
    }

    $Winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $Winget) {
        throw "FFmpeg/FFprobe are required. Install WinGet or install FFmpeg with ffprobe, then reopen PowerShell and rerun .\install.ps1 -Mvp."
    }
    Write-Step "Installing FFmpeg with winget"
    & $Winget.Source install --id Gyan.FFmpeg --exact --source winget `
        --accept-package-agreements --accept-source-agreements
    if (Add-DiscoveredFfmpegToPath) {
        Write-Host "FFmpeg and FFprobe are ready."
        return $true
    }
    throw "FFmpeg/FFprobe were not found after WinGet ran (exit code $LASTEXITCODE). Restart PowerShell and rerun .\install.ps1 -Mvp, or install both tools manually."
}

Set-Location -LiteralPath $InstallerRoot
Write-Host "Meet2Notes installer" -ForegroundColor Blue
Write-Host "Private local transcription, diarization, and meeting summaries"

if (-not (Test-Path -LiteralPath $EnvironmentPython)) {
    Write-Step "Creating the isolated Python environment"
    $Bootstrap = Get-BootstrapPython
    $BootstrapCommand = $Bootstrap[0]
    $BootstrapArguments = @()
    if ($Bootstrap.Count -gt 1) {
        $BootstrapArguments += $Bootstrap[1]
    }
    $BootstrapArguments += @("-m", "venv", $EnvironmentRoot)
    Invoke-Checked $BootstrapCommand $BootstrapArguments
}

$PythonVersion = & $EnvironmentPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0) {
    throw "The Meet2Notes virtual environment is not usable."
}
$VersionParts = $PythonVersion.Trim().Split(".")
if ([int]$VersionParts[0] -lt 3 -or (
    [int]$VersionParts[0] -eq 3 -and [int]$VersionParts[1] -lt 11
)) {
    throw "Meet2Notes requires Python 3.11 or newer."
}

if ($Mvp) {
    Write-Step "Installing the lean meeting MVP"
    $MediaToolsReady = Install-Ffmpeg
    Invoke-Checked $EnvironmentPython @(
        "-m", "pip", "install", "-e", ".[capture,transcription]"
    )
    if ($InstallDiarization) {
        Write-Step "Installing optional Sherpa-ONNX speaker diarization"
        Invoke-Checked $EnvironmentPython @(
            "-m", "pip", "install", "-e", ".[diarization]"
        )
    }
    if ($Dev) {
        Invoke-Checked $EnvironmentPython @("-m", "pip", "install", "-e", ".[dev]")
    }
    if (-not $SkipModels) {
        Write-Step "Downloading and verifying Faster Whisper '$WhisperModel'"
        $ModelArguments = @(
            "-m", "local_meeting_ai.model_setup",
            "--models", "whisper"
        )
        if ($InstallDiarization) { $ModelArguments += "diarization" }
        $ModelArguments += @("--whisper-model", $WhisperModel)
        if ($ModelsDirectory) { $ModelArguments += @("--models-dir", $ModelsDirectory) }
        Invoke-Checked $EnvironmentPython $ModelArguments
    } elseif ($InstallDiarization) {
        Write-Warning "Diarization runtime installed, but its models were skipped. Install them from Settings after setup."
    }
    Write-Step "Verifying the meeting MVP installation"
    Invoke-Checked $EnvironmentPython @("-m", "pip", "check")
    $CheckArguments = @("scripts/check_environment.py")
    if ($ModelsDirectory) { $CheckArguments += @("--models-dir", $ModelsDirectory) }
    if (-not $SkipModels) { $CheckArguments += @("--require-whisper-model", $WhisperModel) }
    if (-not $MediaToolsReady) { $CheckArguments += "--allow-missing-media-tools" }
    Invoke-Checked $EnvironmentPython $CheckArguments
    Write-Host ""
    if ($SkipModels -or -not $MediaToolsReady) {
        Write-Warning "Installation is incomplete for transcription. Resolve the missing items shown above before using it."
    } else {
        Write-Host "Meeting MVP ready for local transcription with Faster Whisper '$WhisperModel'." -ForegroundColor Green
    }
    Write-Host "Choose the finalized-meeting export folder in Settings before your first real meeting."
    Write-Host "Optional: rerun with -InstallDiarization to install Sherpa-ONNX speaker support."
    Write-Host "Optional local AI summaries require a compatible llama-cpp-python runtime; configure and verify separately in Settings."
    Write-Host "Open the local interface with: .\start.bat"
    if ($Start) {
        & (Join-Path $EnvironmentRoot "Scripts\meet2notes.exe")
    }
    return
}

Write-Step "Installing Meet2Notes and native audio/AI runtimes"
Invoke-Checked $EnvironmentPython @("-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel")

$ResolvedBackend = $AiBackend
$NvidiaAvailable = [bool](Get-Command nvidia-smi -ErrorAction SilentlyContinue)
$CudaWheelCompatible = (
    [int]$VersionParts[0] -eq 3 -and
    [int]$VersionParts[1] -ge 10 -and
    [int]$VersionParts[1] -le 12
)
if ($ResolvedBackend -eq "auto") {
    $ResolvedBackend = if ($NvidiaAvailable -and $CudaWheelCompatible) {
        "cuda"
    } else {
        "cpu"
    }
}
if ($ResolvedBackend -eq "cuda" -and -not $NvidiaAvailable) {
    if ($AiBackend -eq "cuda") {
        throw "No NVIDIA driver was detected. Install the driver or use -AiBackend cpu."
    }
    $ResolvedBackend = "cpu"
}

$TorchVersion = if ($ResolvedBackend -eq "cuda") { "2.13.0+cu126" } else { "2.13.0+cpu" }
$TorchIndex = if ($ResolvedBackend -eq "cuda") {
    "https://download.pytorch.org/whl/cu126"
} else {
    "https://download.pytorch.org/whl/cpu"
}
Write-Step "Installing PyTorch $ResolvedBackend runtime inside .venv"
Invoke-Checked $EnvironmentPython @(
    "-m", "pip", "install", "--upgrade", "--force-reinstall", "--no-cache-dir",
    "--progress-bar", "off", "--disable-pip-version-check", "torch==$TorchVersion",
    "--index-url", $TorchIndex
)

Invoke-Checked $EnvironmentPython @(
    "-m", "pip", "install", "-e", ".[capture,transcription,diarization,nvidia-asr,pyannote-diarization]"
)
Invoke-Checked $EnvironmentPython @(
    "-m", "pip", "install", "huggingface-hub>=0.27,<2"
)

$LlamaBackend = if ($ResolvedBackend -eq "cuda" -and $CudaWheelCompatible) {
    "cuda"
} else {
    "cpu"
}
if ($ResolvedBackend -eq "cuda" -and $LlamaBackend -eq "cpu") {
    Write-Warning "CUDA PyTorch is installed for transcription models, but the prebuilt llama.cpp CUDA wheel requires Python 3.10-3.12. Local summaries will use CPU."
}
$LlamaIndex = if ($LlamaBackend -eq "cuda") {
    "https://abetlen.github.io/llama-cpp-python/whl/cu124"
} else {
    "https://abetlen.github.io/llama-cpp-python/whl/cpu"
}
Write-Host "PyTorch backend: $ResolvedBackend"
Write-Host "llama.cpp backend: $LlamaBackend"
& $EnvironmentPython -m pip install "llama-cpp-python>=0.3.8,<1" `
    --extra-index-url $LlamaIndex
if ($LASTEXITCODE -ne 0 -and $AiBackend -eq "auto" -and $LlamaBackend -eq "cuda") {
    Write-Warning "CUDA wheel installation failed; falling back to the portable CPU wheel."
    Invoke-Checked $EnvironmentPython @(
        "-m", "pip", "install", "--force-reinstall",
        "llama-cpp-python>=0.3.8,<1",
        "--extra-index-url",
        "https://abetlen.github.io/llama-cpp-python/whl/cpu"
    )
} elseif ($LASTEXITCODE -ne 0) {
    throw "llama-cpp-python could not be installed for backend '$ResolvedBackend'."
}

if ($Dev) {
    Write-Step "Installing development tools"
    Invoke-Checked $EnvironmentPython @("-m", "pip", "install", "-e", ".[dev]")
}

$MediaToolsReady = Install-Ffmpeg

if ($Models -eq "all") {
    Write-Step "Downloading and verifying the recommended local AI models"
    $ModelArguments = @(
        "-m", "local_meeting_ai.model_setup",
        "--models", "all",
        "--whisper-model", $WhisperModel
    )
    if ($ModelsDirectory) {
        $ModelArguments += @("--models-dir", $ModelsDirectory)
    }
    Invoke-Checked $EnvironmentPython $ModelArguments
}

Write-Step "Verifying the installation"
Invoke-Checked $EnvironmentPython @("-m", "pip", "check")
$CheckArguments = @("scripts/check_environment.py")
if ($Models -eq "all") { $CheckArguments += @("--require-whisper-model", $WhisperModel) }
if ($ModelsDirectory) { $CheckArguments += @("--models-dir", $ModelsDirectory) }
if (-not $MediaToolsReady) { $CheckArguments += "--allow-missing-media-tools" }
Invoke-Checked $EnvironmentPython $CheckArguments

Write-Host ""
if ($Models -eq "none" -or -not $MediaToolsReady) {
    Write-Warning "The runtime is installed, but transcription readiness is incomplete."
} else {
    Write-Host "Meet2Notes is ready for local transcription with Faster Whisper '$WhisperModel'." -ForegroundColor Green
}
Write-Host "Run: .\start.bat"

if ($Start) {
    & (Join-Path $EnvironmentRoot "Scripts\meet2notes.exe")
}

[CmdletBinding()]
param(
    [switch]$SkipModelWarmup
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Get-PythonCommand {
    $candidates = @(
        @{ Name = "py"; Args = @("-3.11") },
        @{ Name = "py"; Args = @("-3") },
        @{ Name = "python"; Args = @() }
    )

    foreach ($candidate in $candidates) {
        if (-not (Get-Command $candidate.Name -ErrorAction SilentlyContinue)) {
            continue
        }

        try {
            & $candidate.Name @($candidate.Args + @("-c", "import sys; print(sys.version_info[:2])")) | Out-Null
            if ($LASTEXITCODE -eq 0) {
                return $candidate
            }
        } catch {
            continue
        }
    }

    throw "Python was not found. Install Python 3.11+ and rerun setup."
}

function Invoke-Python {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & $script:Python.Name @($script:Python.Args + $Arguments)
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed: $($Arguments -join ' ')"
    }
}

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

$script:Python = Get-PythonCommand
$venvPython = Join-Path $repoRoot "venv\Scripts\python.exe"
$venvActivate = Join-Path $repoRoot "venv\Scripts\Activate.ps1"
$envFile = Join-Path $repoRoot ".env"
$envExample = Join-Path $repoRoot ".env.example"

Write-Step "Using repo root $repoRoot"

if (-not (Test-Path $venvPython)) {
    Write-Step "Creating virtual environment"
    Invoke-Python -Arguments @("-m", "venv", "venv")
} else {
    Write-Step "Virtual environment already exists"
}

Write-Step "Upgrading pip"
& $venvPython -m pip install --disable-pip-version-check --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Failed to upgrade pip."
}

Write-Step "Installing Python dependencies"
& $venvPython -m pip install --disable-pip-version-check -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install requirements."
}

if (-not (Test-Path $envFile)) {
    if (-not (Test-Path $envExample)) {
        throw ".env.example was not found."
    }

    Write-Step "Creating .env from .env.example"
    Copy-Item $envExample $envFile
} else {
    Write-Step ".env already exists"
}

if (-not $SkipModelWarmup) {
    Write-Step "Warming up embedding and reranker models"
    $env:HF_HUB_OFFLINE = "0"
    $env:TRANSFORMERS_OFFLINE = "0"

    @'
from sentence_transformers import SentenceTransformer, CrossEncoder

SentenceTransformer("all-MiniLM-L6-v2")
CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
print("models=ready")
'@ | & $venvPython -

    if ($LASTEXITCODE -ne 0) {
        throw "Model warmup failed. Re-run setup with internet access or use -SkipModelWarmup."
    }
} else {
    Write-Step "Skipping model warmup"
}

Write-Step "Setup complete"
Write-Host "Next steps:" -ForegroundColor Green
Write-Host "1. Edit .env and set your real GEMINI_API_KEY if needed."
Write-Host "2. Make sure MongoDB is running on 27017 and Chroma is running on 8001."
Write-Host "3. Activate the venv: $venvActivate"
Write-Host "4. Start the app: python run.py"

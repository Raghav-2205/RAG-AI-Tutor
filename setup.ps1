[CmdletBinding()]
param(
    [switch]$SkipModelWarmup,
    [switch]$SkipAppStart,
    [switch]$SeedLmsDemo
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Ensure-Command {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$FriendlyName
    )

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$FriendlyName was not found. Install it and rerun setup."
    }
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

function Ensure-DockerReady {
    Ensure-Command -Name "docker" -FriendlyName "Docker"

    & docker info | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Desktop is not running. Start Docker and rerun setup."
    }
}

function Ensure-DockerVolume {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    & docker volume create $Name | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create or reuse Docker volume '$Name'."
    }
}

function Ensure-DockerContainer {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$Image,
        [Parameter(Mandatory = $true)]
        [string[]]$RunArguments
    )

    $allContainers = @(& docker ps -a --format "{{.Names}}")
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to query Docker containers."
    }

    if ($allContainers -contains $Name) {
        $runningContainers = @(& docker ps --format "{{.Names}}")
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to query running Docker containers."
        }

        if ($runningContainers -contains $Name) {
            Write-Step "Docker container '$Name' is already running"
        } else {
            Write-Step "Starting existing Docker container '$Name'"
            & docker start $Name | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to start Docker container '$Name'."
            }
        }

        return
    }

    Write-Step "Creating Docker container '$Name'"
    & docker run -d --name $Name @RunArguments $Image | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create Docker container '$Name'."
    }
}

function Wait-ForTcpPort {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Hostname,
        [Parameter(Mandatory = $true)]
        [int]$Port,
        [int]$TimeoutSeconds = 60
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)

    while ((Get-Date) -lt $deadline) {
        $client = $null
        try {
            $client = [System.Net.Sockets.TcpClient]::new()
            $async = $client.BeginConnect($Hostname, $Port, $null, $null)
            $connected = $async.AsyncWaitHandle.WaitOne(1000)
            if ($connected) {
                $client.EndConnect($async)
                $client.Close()
                return
            }
        } catch {
            if ($client) {
                $client.Close()
            }
        }

        Start-Sleep -Seconds 1
    }

    throw "Timed out waiting for ${Hostname}:$Port to become available."
}

function Warn-IfPlaceholderGeminiKey {
    param(
        [Parameter(Mandatory = $true)]
        [string]$EnvFilePath
    )

    if (-not (Test-Path $EnvFilePath)) {
        return
    }

    $content = Get-Content $EnvFilePath -Raw
    if ($content -match 'GEMINI_API_KEY\s*=\s*"?your-gemini-api-key-here"?') {
        Write-Warning "GEMINI_API_KEY is still the placeholder value in .env. The app will start, but Gemini-powered features will not work until you set a real key."
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

Warn-IfPlaceholderGeminiKey -EnvFilePath $envFile

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

Write-Step "Ensuring Docker services"
Ensure-DockerReady
Ensure-DockerVolume -Name "rag_mongo_data"
Ensure-DockerVolume -Name "rag_chroma_data"
Ensure-DockerContainer -Name "rag-mongodb" -Image "mongo:7.0" -RunArguments @("-p", "27017:27017", "-v", "rag_mongo_data:/data/db")
Ensure-DockerContainer -Name "rag-chroma" -Image "chromadb/chroma" -RunArguments @("-p", "8001:8000", "-v", "rag_chroma_data:/chroma/chroma")

Write-Step "Waiting for MongoDB and Chroma to become available"
Wait-ForTcpPort -Hostname "127.0.0.1" -Port 27017
Wait-ForTcpPort -Hostname "127.0.0.1" -Port 8001

Write-Step "Setup complete"
Write-Host "Configured services:" -ForegroundColor Green
Write-Host "- MongoDB: 127.0.0.1:27017"
Write-Host "- Chroma: 127.0.0.1:8001"
Write-Host "- App URL: http://127.0.0.1:8002"

if ($SeedLmsDemo) {
    Write-Step "Seeding LMS demo data"
    & $venvPython "scripts\seed_lms.py" "--reset"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to seed LMS demo data."
    }

    Write-Host "Demo credentials:" -ForegroundColor Green
    Write-Host "- Teacher: lms.teacher@example.com / Password@123"
    Write-Host "- Students: lms.student1@example.com ... lms.student8@example.com / Password@123"
}

if ($SkipAppStart) {
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Green
    Write-Host "1. Edit .env and set your real GEMINI_API_KEY if needed."
    Write-Host "2. Activate the venv: $venvActivate"
    Write-Host "3. Optional demo seed: python scripts/seed_lms.py --reset"
    Write-Host "4. Start the app: python run.py"
    return
}

Write-Step "Starting the app"
Write-Host "Press Ctrl+C to stop the app. Docker containers will keep running." -ForegroundColor Yellow
& $venvPython run.py
if ($LASTEXITCODE -ne 0) {
    throw "The app exited with a non-zero status."
}

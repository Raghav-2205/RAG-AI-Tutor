[CmdletBinding()]
param(
    [string]$OutputDir = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $OutputDir) {
    $OutputDir = Join-Path (Split-Path -Parent $repoRoot) "RAG-AI-Tutor-runtime"
}

$keepItems = @(
    ".env.example",
    ".gitignore",
    "README.md",
    "requirements.txt",
    "run.py",
    "setup.ps1",
    "backend",
    "frontend"
)

if (Test-Path $OutputDir) {
    if (-not $Force) {
        throw "Output directory already exists: $OutputDir. Use -Force to recreate it."
    }

    Remove-Item $OutputDir -Recurse -Force
}

New-Item -ItemType Directory -Path $OutputDir | Out-Null

foreach ($item in $keepItems) {
    $source = Join-Path $repoRoot $item
    if (-not (Test-Path $source)) {
        Write-Warning "Skipping missing item: $item"
        continue
    }

    $destination = Join-Path $OutputDir $item
    Copy-Item $source $destination -Recurse -Force
}

Write-Host "Runtime-only export created at: $OutputDir" -ForegroundColor Green
Write-Host "Included items:" -ForegroundColor Cyan
$keepItems | ForEach-Object { Write-Host " - $_" }

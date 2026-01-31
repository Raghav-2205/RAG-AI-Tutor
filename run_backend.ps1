# Run RAG AI Tutor backend on port 8000
# Usage: .\run_backend.ps1
# Then open: http://localhost:8000/chatbot.html

Set-Location $PSScriptRoot

Write-Host "Installing dependencies if needed..." -ForegroundColor Cyan
pip install -r requirements.txt 2>$null

Write-Host "Starting backend on http://localhost:8000 ..." -ForegroundColor Green
Write-Host "Chat interface: http://localhost:8000/chatbot.html" -ForegroundColor Yellow
Write-Host "Press CTRL+C to stop." -ForegroundColor Gray
# Use python -m uvicorn (works when uvicorn not on PATH). No --reload to avoid Windows multiprocessing errors.
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

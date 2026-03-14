#!/bin/bash
# Production deployment script for RAG AI Tutor
# Supports Docker, systemd, nginx reverse proxy

set -e  # Exit on any error

echo "🚀 Deploying RAG AI Tutor to Production..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
BACKEND_PORT=8000
FRONTEND_PORT=3000
DB_PATH="rag_ai_tutor.db"

log() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 1. BACKUP DATABASE
log "📦 Creating database backup..."
python3 scripts/backup_db.py || warn "Backup failed, continuing..."

# 2. PULL LATEST CODE (if git repo)
if [ -d ".git" ]; then
    log "🔄 Pulling latest code..."
    git pull origin main || warn "Git pull failed"
fi

# 3. INSTALL DEPENDENCIES
log "📦 Installing Python dependencies..."
pip3 install -r requirements.txt --upgrade

# 4. DOWNLOAD/UPDATE MODELS
log "🧠 Updating AI models..."
python3 scripts/download_models.py

# 5. MIGRATE DATABASE
log "🗄️  Running database migrations..."
python3 -c "
from backend.main import app
import backend.database
backend.database.init_db()
print('✅ Database ready')
"

# 6. BUILD FRONTEND (if needed)
if [ -d "frontend" ]; then
    log "🏗️  Building frontend..."
    cd frontend && npm install && npm run build && cd ..
fi

# 7. START SERVICES
log "⚙️  Starting services..."

# Backend with uvicorn
if command -v supervisor &> /dev/null; then
    supervisorctl restart rag-ai-backend || supervisorctl start rag-ai-backend
else
    nohup uvicorn backend.main:app --host 0.0.0.0 --port $BACKEND_PORT --workers 4 > backend.log 2>&1 &
fi

# Frontend static server
nohup python3 -m http.server $FRONTEND_PORT -d frontend/public > frontend.log 2>&1 &

# 8. NGINX CONFIG (if present)
if command -v nginx &> /dev/null; then
    log "🌐 Configuring nginx..."
    sudo cp nginx/rag-ai.conf /etc/nginx/sites-available/rag-ai
    sudo ln -sf /etc/nginx/sites-available/rag-ai /etc/nginx/sites-enabled/
    sudo nginx -t && sudo systemctl reload nginx
fi

# 9. FINAL CHECKS
log "✅ Deployment complete!"
log "🔗 Backend: http://localhost:$BACKEND_PORT"
log "🔗 Frontend: http://localhost:$FRONTEND_PORT"
log "📊 Check logs: tail -f backend.log frontend.log"

# Health check
sleep 3
curl -f http://localhost:$BACKEND_PORT/health || warn "Health check failed"

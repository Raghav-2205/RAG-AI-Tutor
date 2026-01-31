"""
FastAPI application: serves frontend static files and API.
Run: uvicorn backend.main:app --reload --port 8000
"""
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.config import settings
from backend.api import auth_router, chat_router

app = FastAPI(
    title="RAG AI Tutor API",
    description="OpenLearnHub / RAG AI Tutor backend",
    version="0.1.0",
)

# CORS so chat works from browser (same-origin and common dev origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routers
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(chat_router, prefix="/api/chat", tags=["chat"])

# Frontend: mount static assets (JS, CSS, etc.)
frontend_public = settings.frontend_public
if frontend_public.exists():
    app.mount("/src", StaticFiles(directory=frontend_public.parent / "src"), name="src")

# Serve HTML pages from frontend/public
_index_path = frontend_public / "index.html"
_static_fallback = ["login.html", "signup.html", "subjects.html", "index.html"]


@app.get("/")
def serve_index():
    """Serve index.html at root."""
    if _index_path.exists():
        return FileResponse(_index_path)
    return {"message": "RAG AI Tutor API", "docs": "/docs"}


@app.get("/index.html")
def serve_index_html():
    if _index_path.exists():
        return FileResponse(_index_path)
    return {"message": "RAG AI Tutor API"}


@app.get("/login.html")
def serve_login():
    p = frontend_public / "login.html"
    if p.exists():
        return FileResponse(p)
    raise HTTPException(status_code=404, detail="Not found")


@app.get("/signup.html")
def serve_signup():
    p = frontend_public / "signup.html"
    if p.exists():
        return FileResponse(p)
    raise HTTPException(status_code=404, detail="Not found")


@app.get("/subjects.html")
def serve_subjects():
    p = frontend_public / "subjects.html"
    if p.exists():
        return FileResponse(p)
    raise HTTPException(status_code=404, detail="Not found")


@app.get("/chatbot.html")
def serve_chatbot():
    p = frontend_public / "chatbot.html"
    if p.exists():
        return FileResponse(p)
    raise HTTPException(status_code=404, detail="Not found")


@app.get("/manifest.json")
def serve_manifest():
    p = frontend_public / "manifest.json"
    if p.exists():
        return FileResponse(p)
    return {"name": "OpenLearnHub"}, 200


@app.get("/health")
def health():
    return {"status": "ok", "service": "rag-ai-tutor"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)

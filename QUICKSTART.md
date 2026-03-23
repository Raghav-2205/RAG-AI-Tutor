# 🚀 RAG AI Tutor: Quick Start Guide

This guide provides the essential commands to set up and run the RAG AI Tutor project on Windows.

## 🛠️ First-Time Setup
Run the automated setup script. This will create the virtual environment, install dependencies, download models, and start Docker containers.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

> [!IMPORTANT]
> Ensure **Docker Desktop** is running before executing the setup.

---

## 🏃 Running the Application
If you have already run the setup and just want to start the app again:

### 1. Start Docker Services (if not running)
```powershell
docker start rag-mongodb rag-chroma
```

### 2. Activate Virtual Environment & Run
```powershell
.\venv\Scripts\Activate.ps1
python run.py
```

**Access the App:** [http://127.0.0.1:8002](http://127.0.0.1:8002)

---

## 🛑 Stopping the Project
1.  **Stop the App**: Press `Ctrl + C` in the terminal.
2.  **Stop Docker Containers**:
```powershell
docker stop rag-mongodb rag-chroma
```

---

## ⚙️ Configuration
Remember to set your `GEMINI_API_KEY` in the `.env` file for AI features to work:
```env
GEMINI_API_KEY=your_key_here
```

# RAG AI Tutor

A Retrieval-Augmented Generation (RAG) AI tutoring system that provides personalized learning experiences using your own documents.

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- MongoDB (local or Atlas)
- Git

### 1. Clone and Setup
```bash
git clone <repository-url>
cd rag-ai-tutor
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure Environment
```bash
# Copy environment template
cp .env.example .env

# Edit .env with your settings
nano .env  # or your preferred editor
```

### 4. Start the Application
```bash
# Option 1: Use startup script (recommended)
python start_server.py

# Option 2: Manual start
python -m uvicorn backend.main:app --reload
```

### 5. Access the Application
- **Frontend**: http://127.0.0.1:8000
- **API Documentation**: http://127.0.0.1:8000/docs
- **Health Check**: http://127.0.0.1:8000/health

## 🏗️ Architecture

### Frontend-Backend-Database Connection Flow

```
Frontend (Vanilla JS SPA)
    ↓ HTTP/WebSocket
Backend (FastAPI)
    ↓ Motor (async MongoDB driver)
Database (MongoDB)
    ↓ Vector embeddings
ChromaDB (Vector Database)
    ↓ AI Processing
Gemini API (Google AI)
```

### Key Components

1. **Frontend** (`frontend/public/`)
   - Single Page Application with vanilla JavaScript
   - Modular component architecture
   - Environment-aware configuration
   - Enhanced error handling and user feedback

2. **Backend** (`backend/`)
   - FastAPI with async/await support
   - JWT-based authentication
   - Modular API routers
   - Comprehensive error handling
   - Database connection pooling

3. **Database** (MongoDB + ChromaDB)
   - MongoDB for user data, chat history, documents
   - ChromaDB for vector embeddings
   - Proper indexing for performance
   - Connection management and health checks

## 🔧 Configuration

### Environment Variables (.env)

```bash
# App Settings
APP_NAME="RAG AI Tutor"
DEBUG=true

# Database
MONGODB_URI="mongodb://localhost:27017"
DATABASE_NAME="rag_ai_tutor"

# API Settings
API_HOST="127.0.0.1"
API_PORT=8000

# Security
SECRET_KEY="your-secret-key-here"
ACCESS_TOKEN_EXPIRE_MINUTES=30

# AI/ML
GEMINI_API_KEY="your-gemini-api-key"
EMBEDDING_MODEL="all-MiniLM-L6-v2"

# File Upload
MAX_FILE_SIZE=10485760  # 10MB
ALLOWED_EXTENSIONS=".pdf,.docx,.txt"

# CORS (for production)
ALLOWED_ORIGINS="http://localhost:3000,https://yourdomain.com"
```

### MongoDB Setup

#### Local MongoDB
```bash
# Install MongoDB Community Edition
# macOS
brew install mongodb-community

# Ubuntu
sudo apt install mongodb

# Start MongoDB
mongod --dbpath /path/to/data/directory
```

#### MongoDB Atlas (Cloud)
1. Create account at https://cloud.mongodb.com
2. Create cluster
3. Get connection string
4. Update `MONGODB_URI` in `.env`

## 📁 Project Structure

```
rag-ai-tutor/
├── backend/
│   ├── api/                 # API routers
│   │   ├── auth.py         # Authentication endpoints
│   │   ├── chat.py         # Chat/RAG endpoints
│   │   ├── upload.py       # File upload endpoints
│   │   ├── quiz.py         # Quiz generation
│   │   └── feedback.py     # User feedback
│   ├── core/               # Core services
│   │   ├── embedding_service.py
│   │   ├── llm_interface.py
│   │   └── search_engine.py
│   ├── models/             # Pydantic models
│   ├── utils/              # Utilities
│   │   ├── db.py          # Database manager
│   │   ├── validators.py   # Input validation
│   │   └── helpers.py      # Helper functions
│   ├── config.py           # Configuration management
│   └── main.py            # FastAPI application
├── frontend/
│   └── public/
│       ├── assets/
│       │   ├── js/
│       │   │   ├── config.js    # Environment config
│       │   │   ├── auth.js      # Authentication
│       │   │   ├── ai.js        # AI chat manager
│       │   │   └── ...
│       │   └── css/
│       ├── views/          # HTML templates
│       └── index.html      # Main SPA entry
├── database/               # Database scripts
├── docs/                   # Documentation
├── .env.example           # Environment template
├── requirements.txt       # Python dependencies
├── start_server.py       # Startup script
└── test_connections.py   # Connection tests
```

## 🔌 API Endpoints

### Authentication
- `POST /api/auth/register` - User registration
- `POST /api/auth/login` - User login (JWT)
- `GET /api/auth/me` - Current user info
- `POST /api/auth/refresh` - Refresh token

### Chat & RAG
- `POST /api/chat` - Send message to AI tutor
- `GET /api/chat/sessions` - Get chat sessions
- `POST /api/chat/sessions` - Create new session
- `GET /api/chat/history/{session_id}` - Get chat history

### Document Management
- `POST /api/upload` - Upload document
- `GET /api/upload` - List user documents
- `DELETE /api/upload/{doc_id}` - Delete document

### Quiz Generation
- `POST /api/quiz/generate` - Generate quiz from documents
- `GET /api/quiz/{quiz_id}` - Get quiz details

### Feedback
- `POST /api/feedback` - Submit user feedback

## 🧪 Testing

### Run Connection Tests
```bash
# Test all connections
python test_connections.py

# Test with running server
python test_connections.py --test-server
```

### Manual Testing
```bash
# Test API health
curl http://127.0.0.1:8000/health

# Test authentication
curl -X POST http://127.0.0.1:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"testpass123","name":"Test User","level":"undergraduate"}'
```

## 🚀 Deployment

### Development
```bash
python start_server.py
```

### Production

#### Using Docker
```bash
# Build and run
docker-compose up -d
```

#### Manual Production Setup
1. Set `DEBUG=false` in `.env`
2. Configure production MongoDB URI
3. Set secure `SECRET_KEY`
4. Configure CORS origins
5. Use production WSGI server:
```bash
gunicorn backend.main:app -w 4 -k uvicorn.workers.UvicornWorker
```

## 🔧 Troubleshooting

### Common Issues

#### Database Connection Failed
```bash
# Check MongoDB is running
mongosh --eval "db.adminCommand('ping')"

# Check connection string in .env
echo $MONGODB_URI
```

#### Frontend Can't Connect to Backend
- Check API base URL in browser console
- Verify CORS settings in `backend/config.py`
- Check if backend is running on correct port

#### File Upload Issues
- Check `MAX_FILE_SIZE` setting
- Verify `uploads/` directory exists and is writable
- Check file extension in `ALLOWED_EXTENSIONS`

#### AI Features Not Working
- Verify `GEMINI_API_KEY` is set correctly
- Check API quota and billing
- Review logs for specific error messages

### Debug Mode
```bash
# Enable debug logging
DEBUG=true python start_server.py

# Check logs
tail -f rag-ai-backend.log
```

## 🤝 Contributing

1. Fork the repository
2. Create feature branch: `git checkout -b feature-name`
3. Make changes and test
4. Submit pull request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🆘 Support

- **Documentation**: Check `/docs` folder
- **API Docs**: http://127.0.0.1:8000/docs
- **Issues**: Create GitHub issue
- **Health Check**: http://127.0.0.1:8000/health
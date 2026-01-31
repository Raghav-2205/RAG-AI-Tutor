# RAG AI Tutor

A Retrieval-Augmented Generation (RAG) AI Tutoring System that provides personalized educational assistance with document upload, Socratic tutoring, quiz generation, and feedback collection.

## Features

- 📚 **Document Processing**: Upload PDFs, DOCX, TXT, and images with OCR support
- 🤖 **Socratic Tutoring**: AI-powered tutoring that guides students through questions rather than giving direct answers
- 🔍 **Hybrid Search**: Combines BM25 keyword search with dense vector embeddings for accurate retrieval
- 📝 **Quiz Generation**: Automatically generate quizzes from uploaded documents
- 💬 **Interactive Chat**: Real-time chat interface with citation support
- 🎯 **Multi-Subject Support**: Configurable subjects (CS, Math, Physics, Biology, Chemistry)
- 🔐 **User Authentication**: Secure user accounts with JWT authentication
- 📊 **Feedback System**: Collect and analyze user feedback

## Architecture

### Backend
- **Framework**: FastAPI (Python)
- **Database**: MongoDB (structured data) + ChromaDB (vector embeddings)
- **LLM**: Gemini 1.5 Flash (configurable: Groq, OpenAI)
- **Embeddings**: Sentence Transformers (all-MiniLM-L6-v2)
- **Search**: Hybrid BM25 + Dense Vector + Reranking

### Frontend
- **Framework**: Vanilla JavaScript
- **Styling**: CSS3
- **Features**: Real-time chat, file upload, voice input

## Installation

### Prerequisites

- Python 3.11+
- MongoDB 7.0+
- Node.js (for frontend, optional)
- API Keys:
  - Gemini API Key (recommended)
  - Or Groq API Key
  - Or OpenAI API Key

### Setup

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd "RAG AI TUTOR"
   ```

2. **Run setup script**
   ```bash
   python scripts/setup.py
   ```

3. **Install Python dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Download ML models** (optional, will download on first use)
   ```bash
   python scripts/download_models.py
   ```

5. **Configure environment variables**
   ```bash
   cp .env.example .env
   # Edit .env and add your API keys
   ```

6. **Start MongoDB**
   ```bash
   # Using Docker
   docker run -d -p 27017:27017 --name mongodb mongo:7.0
   
   # Or use local MongoDB installation
   mongod
   ```

7. **Run the application**
   ```bash
   python -m backend.main
   ```

   Or using uvicorn directly:
   ```bash
   uvicorn backend.main:app --reload
   ```

8. **Access the application**
   - Frontend: http://localhost:8000
   - API Docs: http://localhost:8000/docs

## Docker Deployment

1. **Build and run with Docker Compose**
   ```bash
   docker-compose up -d
   ```

2. **Access the application**
   - Frontend: http://localhost:3000
   - Backend API: http://localhost:8000

## Configuration

### Environment Variables

Create a `.env` file with the following variables:

```env
# API Keys
GEMINI_API_KEY=your_gemini_api_key_here
GROQ_API_KEY=your_groq_api_key_here  # Optional
OPENAI_API_KEY=your_openai_api_key_here  # Optional

# Database
MONGODB_URI=mongodb://localhost:27017

# Application
DEBUG=true
SECRET_KEY=your_secret_key_here
JWT_SECRET_KEY=your_jwt_secret_key_here
```

### Configuration Files

- `config/config.yaml` - Main configuration
- `config/development.yaml` - Development settings
- `config/production.yaml` - Production settings
- `config/models_config.yaml` - LLM and embedding model settings
- `config/subjects_config.yaml` - Subject-specific configurations

## Usage

### 1. Register/Login

- Navigate to http://localhost:8000/static/login.html
- Create an account or login

### 2. Upload Documents

- Click "Upload Document" button
- Select PDF, DOCX, TXT, or image files
- Documents are automatically processed and indexed

### 3. Chat with AI Tutor

- Type questions in the chat interface
- The AI will provide Socratic guidance based on your uploaded documents
- Responses include citations to source materials

### 4. Generate Quizzes

- Use the quiz generation feature to create quizzes from your documents
- Select difficulty level and number of questions
- Take the quiz and get instant feedback

### 5. Provide Feedback

- Rate responses and provide feedback
- Help improve the system

## API Endpoints

### Authentication
- `POST /api/auth/register` - Register new user
- `POST /api/auth/login` - Login user
- `GET /api/auth/me` - Get current user

### Documents
- `POST /api/upload/` - Upload document
- `GET /api/upload/` - List documents
- `DELETE /api/upload/{document_id}` - Delete document

### Chat
- `POST /api/chat/` - Send message
- `GET /api/chat/stream` - Stream response
- `GET /api/chat/sessions` - List chat sessions
- `GET /api/chat/sessions/{chat_id}` - Get chat session

### Quiz
- `POST /api/quiz/generate` - Generate quiz
- `GET /api/quiz/` - List quizzes
- `GET /api/quiz/{quiz_id}` - Get quiz
- `POST /api/quiz/{quiz_id}/submit` - Submit quiz

### Feedback
- `POST /api/feedback/` - Create feedback
- `GET /api/feedback/` - List feedback

## Architecture

### RAG Pipeline
1. **Ingestion**: Documents → Text Extraction → Chunking (600 chars, 100 overlap)
2. **Embedding**: Chunks → Embeddings (all-MiniLM-L6-v2)
3. **Storage**: Embeddings → ChromaDB
4. **Retrieval**: Query → Hybrid Search (BM25 + Dense) → Reranking
5. **Generation**: Context + Query → LLM (Gemini) → Socratic Response

### Hybrid Search
- **BM25**: Keyword-based sparse retrieval
- **Dense Vectors**: Semantic similarity search
- **Fusion**: Reciprocal Rank Fusion (RRF)
- **Reranking**: Cross-encoder for final ranking

## Development

### Project Structure

```
RAG AI TUTOR/
├── backend/              # Python FastAPI backend
│   ├── api/              # API endpoints
│   ├── core/             # Core services (LLM, embeddings, OCR, search)
│   ├── models/           # Database models
│   ├── utils/            # Utilities
│   └── main.py           # FastAPI application
├── frontend/             # Frontend files
│   ├── public/           # HTML files
│   └── src/              # JavaScript and CSS
├── config/               # Configuration files
├── data/                 # Data storage
├── scripts/              # Utility scripts
└── requirements.txt      # Python dependencies
```

### Running Tests

```bash
pytest backend/tests/
```

## Performance Targets

- **BERTScore F1**: >0.91
- **Hallucination Rate**: <6.1%
- **Latency**: <2.5s per query

## Troubleshooting

### MongoDB Connection Issues
- Ensure MongoDB is running: `mongod` or `docker ps`
- Check connection string in `.env`

### API Key Issues
- Verify API keys in `.env` file
- Check API key permissions and quotas

### Model Download Issues
- Models download automatically on first use
- Check internet connection
- For offline use, pre-download models: `python scripts/download_models.py`

## License

See LICENSE file for details.

## Contributing

See CONTRIBUTING.md for guidelines.

## References

- RAG-Tutor Paper: [Link to paper]
- Athena: [Reference]
- MARK Hybrid Retrieval: [Reference]

## Support

For issues and questions, please open an issue on GitHub.
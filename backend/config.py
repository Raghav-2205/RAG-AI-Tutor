from pydantic_settings import BaseSettings
from typing import Optional, List
import os

class Settings(BaseSettings):
    # App settings
    app_name: str = "RAG AI Tutor"
    debug: bool = True
    version: str = "1.0.0"
    
    # Database settings
    mongodb_uri: str = "mongodb://localhost:27017"
    database_name: str = "rag_ai_tutor"
    
    # API settings
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_prefix: str = "/api"
    
    # Security settings
    secret_key: str = "your-secret-key-change-in-production"
    jwt_secret_key: str = "jwt-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    
    # AI/ML settings
    gemini_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    embedding_model: str = "all-MiniLM-L6-v2"
    llm_model: str = "gemini-1.5-flash"
    temperature: float = 0.7
    max_tokens: int = 2048
    
    # File upload settings
    upload_dir: str = "uploads"
    max_file_size: int = 10 * 1024 * 1024  # 10MB
    allowed_extensions: str = ".pdf,.docx,.txt,.png,.jpg,.jpeg"  # Comma-separated string
    
    # Vector DB settings
    chroma_persist_directory: str = "chroma_data"
    chunk_size: int = 600
    chunk_overlap: int = 100
    top_k_retrieval: int = 6
    min_similarity_score: float = 0.5
    
    # Search settings
    use_hybrid_search: bool = True
    bm25_weight: float = 0.3
    dense_weight: float = 0.7
    
    # CORS settings
    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:8000,http://localhost:8000"  # Comma-separated string
    
    # Logging
    log_level: str = "INFO"
    log_file: str = "rag-ai-backend.log"
    
    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8'
        extra = 'ignore'
    
    def get_allowed_extensions_list(self) -> List[str]:
        """Convert comma-separated extensions string to list"""
        return [ext.strip() for ext in self.allowed_extensions.split(',')]
    
    def get_allowed_origins_list(self) -> List[str]:
        """Convert comma-separated origins string to list"""
        return [origin.strip() for origin in self.allowed_origins.split(',')]

settings = Settings()

# Validate required settings
if not settings.gemini_api_key:
    print("⚠️  Warning: GEMINI_API_KEY not set. AI features may not work.")

print(f'✅ Config loaded: {settings.app_name} v{settings.version}')
print(f'📊 Database: {settings.mongodb_uri}')
print(f'🌐 API: http://{settings.api_host}:{settings.api_port}{settings.api_prefix}')

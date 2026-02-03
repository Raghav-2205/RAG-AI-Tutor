# backend/config.py
from pydantic_settings import BaseSettings
from typing import List, Optional

class Settings(BaseSettings):
    # App Settings
    app_name: str = "RAG AI Tutor"
    version: str = "1.0.0"
    debug: bool = True
    
    # API Settings
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_prefix: str = "/api"
    
    # Database
    mongodb_uri: str = "mongodb://localhost:27017"
    database_name: str = "rag_ai_tutor"
    
    # Security
    jwt_secret_key: str = "change_this_to_a_random_secret_string"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    
    # AI / RAG
    gemini_api_key: Optional[str] = None
    embedding_model: str = "all-MiniLM-L6-v2"
    
    # File Uploads
    upload_dir: str = "uploads"
    max_file_size: int = 10 * 1024 * 1024  # 10MB
    
    # Vector DB
    chroma_persist_directory: str = "chroma_data"
    chunk_size: int = 600
    chunk_overlap: int = 100

    # CORS
    allowed_origins: str = "http://localhost:8000,http://127.0.0.1:8000"

    def get_allowed_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.allowed_origins.split(',')]

    class Config:
        env_file = ".env"
        extra = "ignore" # Ignore extra fields in .env

settings = Settings()
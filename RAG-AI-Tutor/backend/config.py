from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional

class Settings(BaseSettings):
    app_name: str = "RAG AI Tutor"
    version: str = "1.0.0"
    debug: bool = True
    
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_prefix: str = "/api"
    
    mongodb_uri: str = "mongodb://127.0.0.1:27017"
    database_name: str = "rag_ai_tutor"
    
    jwt_secret_key: str = "secret"
    secret_key: str = "secret"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    
    gemini_api_key: Optional[str] = None
    embedding_model: str = "all-MiniLM-L6-v2"
    
    # Use the safest model tag
    llm_model: str = "gemini-1.5-flash" 
    temperature: float = 0.7
    max_tokens: int = 2048
    
    upload_dir: str = "uploads"
    max_file_size: int = 10 * 1024 * 1024
    allowed_extensions: str = ".pdf,.docx,.txt,.pptx,.ppt,.jpg,.jpeg,.png,.mp3,.wav"
    
    chroma_persist_directory: str = "chroma_data"
    chroma_api_url: str = "http://127.0.0.1:8001/api/v2"
    chroma_tenant: str = "default_tenant"
    chroma_database: str = "default_database"
    chunk_size: int = 600
    chunk_overlap: int = 100
    top_k_retrieval: int = 6
    min_similarity_score: float = 0.5
    use_hybrid_search: bool = True
    bm25_weight: float = 0.5
    dense_weight: float = 0.5

    log_level: str = "INFO"
    log_file: str = "rag-ai-backend.log"
    allowed_origins: str = "*"

    # Ignore extra .env vars
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()

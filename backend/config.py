"""
Backend configuration: load from .env and optional YAML.
"""
import os
from pathlib import Path
from typing import Optional

try:
    from pydantic_settings import BaseSettings
except ImportError:
    from pydantic import BaseSettings  # pydantic v1
from pydantic import Field


class Settings(BaseSettings):
    """Application settings from environment."""

    # App
    debug: bool = Field(default=True, alias="DEBUG")
    secret_key: str = Field(default="change-me-in-production", alias="SECRET_KEY")

    # Database
    mongodb_uri: str = Field(default="mongodb://localhost:27017", alias="MONGODB_URI")

    # Auth
    jwt_secret_key: str = Field(default="jwt-secret-change-me", alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_expire_minutes: int = Field(default=60 * 24 * 7, alias="JWT_EXPIRE_MINUTES")  # 7 days

    # API Keys (optional for Day 1)
    gemini_api_key: Optional[str] = Field(default=None, alias="GEMINI_API_KEY")
    groq_api_key: Optional[str] = Field(default=None, alias="GROQ_API_KEY")
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")

    # Paths
    project_root: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent)
    frontend_public: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent / "frontend" / "public")
    data_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent / "data")
    chroma_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent / "data" / "chroma")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()

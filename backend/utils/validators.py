from typing import Any, List
import re
from pydantic import field_validator
from fastapi import HTTPException

# Valid subjects for the RAG AI Tutor
VALID_SUBJECTS = [
    "mathematics", "physics", "chemistry", "biology", 
    "computer_science", "history", "literature", "economics",
    "psychology", "philosophy", "general"
]

def validate_subject_field(subject: str) -> str:
    """Validate subject field against allowed subjects"""
    if subject and subject.lower() not in VALID_SUBJECTS:
        raise ValueError(f"Subject must be one of: {', '.join(VALID_SUBJECTS)}")
    return subject.lower() if subject else subject

def validate_email(email: str) -> str:
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(pattern, email):
        raise ValueError("Invalid email format")
    return email.lower()

def validate_password(password: str) -> str:
    """Validate password strength"""
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long")
    if not re.search(r'[A-Za-z]', password):
        raise ValueError("Password must contain at least one letter")
    if not re.search(r'\d', password):
        raise ValueError("Password must contain at least one number")
    return password

def validate_file_extension(filename: str, allowed_extensions: List[str]) -> str:
    """Validate file extension"""
    if not any(filename.lower().endswith(ext) for ext in allowed_extensions):
        raise HTTPException(
            status_code=400,
            detail=f"File type not allowed. Allowed types: {', '.join(allowed_extensions)}"
        )
    return filename

def validate_file_size(file_size: int, max_size: int) -> int:
    """Validate file size"""
    if file_size > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size: {max_size / (1024*1024):.1f}MB"
        )
    return file_size

def validate_user_level(level: str) -> str:
    """Validate user education level"""
    valid_levels = ["high_school", "undergraduate", "graduate", "professional"]
    if level.lower() not in valid_levels:
        raise ValueError(f"Level must be one of: {', '.join(valid_levels)}")
    return level.lower()

def sanitize_text(text: str) -> str:
    """Sanitize text input to prevent injection attacks"""
    # Remove potentially dangerous characters
    text = re.sub(r'[<>"\']', '', text)
    # Limit length
    if len(text) > 10000:
        text = text[:10000]
    return text.strip()
from typing import Dict, Any, Optional, List
from datetime import datetime
from bson import ObjectId
import json

def doc_to_dict(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Convert MongoDB document to JSON-serializable dict"""
    if doc is None:
        return {}
    
    # Convert ObjectId to string
    if '_id' in doc:
        doc['id'] = str(doc['_id'])
        del doc['_id']
    
    # Convert datetime objects to ISO strings
    for key, value in doc.items():
        if isinstance(value, datetime):
            doc[key] = value.isoformat()
        elif isinstance(value, ObjectId):
            doc[key] = str(value)
    
    return doc

def docs_to_list(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert list of MongoDB documents to JSON-serializable list"""
    return [doc_to_dict(doc) for doc in docs]

def generate_session_id() -> str:
    """Generate a unique session ID"""
    from uuid import uuid4
    return str(uuid4())

def format_chat_response(message: str, citations: List[Dict] = None) -> Dict[str, Any]:
    """Format chat response with citations"""
    return {
        "message": message,
        "citations": citations or [],
        "timestamp": datetime.now().isoformat()
    }

def extract_text_preview(text: str, max_length: int = 200) -> str:
    """Extract a preview of text content"""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."

def validate_object_id(id_str: str) -> bool:
    """Validate if string is a valid ObjectId"""
    try:
        ObjectId(id_str)
        return True
    except:
        return False

def create_error_response(message: str, code: int = 400) -> Dict[str, Any]:
    """Create standardized error response"""
    return {
        "error": True,
        "message": message,
        "code": code,
        "timestamp": datetime.now().isoformat()
    }

def create_success_response(data: Any = None, message: str = "Success") -> Dict[str, Any]:
    """Create standardized success response"""
    response = {
        "error": False,
        "message": message,
        "timestamp": datetime.now().isoformat()
    }
    if data is not None:
        response["data"] = data
    return response

def paginate_results(results: List[Any], page: int = 1, per_page: int = 20) -> Dict[str, Any]:
    """Paginate results"""
    total = len(results)
    start = (page - 1) * per_page
    end = start + per_page
    
    return {
        "results": results[start:end],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": (total + per_page - 1) // per_page
        }
    }

def clean_filename(filename: str) -> str:
    """Clean filename for safe storage"""
    import re
    # Remove or replace unsafe characters
    filename = re.sub(r'[^\w\-_\.]', '_', filename)
    # Limit length
    if len(filename) > 255:
        name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
        filename = name[:250] + ('.' + ext if ext else '')
    return filename

def get_file_size_mb(file_path: str) -> float:
    """Get file size in MB"""
    import os
    if os.path.exists(file_path):
        return os.path.getsize(file_path) / (1024 * 1024)
    return 0.0
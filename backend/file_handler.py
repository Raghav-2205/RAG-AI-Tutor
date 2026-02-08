import os
from pathlib import Path
from pypdf import PdfReader
from docx import Document as DocxDocument
from pptx import Presentation
from PIL import Image
from backend.config import settings

# Safe imports
try:
    import pytesseract
except ImportError:
    pytesseract = None

try:
    import google.generativeai as genai
    if settings.gemini_api_key:
        genai.configure(api_key=settings.gemini_api_key)
    GENAI_AVAILABLE = True
except (ImportError, TypeError):
    genai = None
    GENAI_AVAILABLE = False


# Ensure upload directory exists
BASE_UPLOAD_DIR = Path(settings.upload_dir)
BASE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

def save_upload_to_disk(filename: str, file_bytes: bytes, user_id: str) -> Path:
    """Saves the uploaded file to a user-specific folder."""
    user_folder = BASE_UPLOAD_DIR / str(user_id)
    user_folder.mkdir(parents=True, exist_ok=True)
    
    # Sanitize filename
    sanitized_name = filename.replace("/", "_").replace("\\", "_")
    full_path = user_folder / sanitized_name
    
    with open(full_path, "wb") as f:
        f.write(file_bytes)
        
    return full_path

def extract_text_from_pdf(path: Path) -> str:
    try:
        reader = PdfReader(str(path))
        return "\n\n".join([p.extract_text() for p in reader.pages if p.extract_text()])
    except Exception as e:
        print(f"Error reading PDF {path}: {e}")
        return ""

def extract_text_from_docx(path: Path) -> str:
    try:
        doc = DocxDocument(str(path))
        return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
    except Exception as e:
        print(f"Error reading DOCX {path}: {e}")
        return ""

def extract_text_from_pptx(path: Path) -> str:
    try:
        prs = Presentation(str(path))
        text = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    text.append(shape.text)
        return "\n".join(text)
    except Exception as e:
        print(f"Error reading PPTX {path}: {e}")
        return ""

def extract_text_from_image(path: Path) -> str:
    try:
        # Try Gemini Vision via REST (Better than Tesseract)
        try:
            from backend.core.llm_interface import llm_client
            with open(path, "rb") as img_file:
                img_bytes = img_file.read()
            
            # Determine mime type roughly
            ext = path.suffix.lower()
            mime = "image/png" if ext == ".png" else "image/jpeg"
            
            response = llm_client.generate_with_image(
                prompt="Transcribe all text from this image exactly.", 
                image_bytes=img_bytes,
                mime_type=mime
            )
            
            if "LLM Request Failed" not in response and "Error" not in response:
                return f"[Image Transcription]\n{response}"
            
        except Exception as e:
            print(f"Gemini Vision REST failed: {e}")
        
        # Fallback to Tesseract
        if pytesseract:
            param = Image.open(path)
            # pytesseract expects path or image object
            return pytesseract.image_to_string(param)
        else:
            return "[Image OCR Failed: Tesseract not installed]"
            
    except Exception as e:
        print(f"Error reading Image {path}: {e}")
        return f"[Image Content - Processing Failed: {e}]"

def extract_text_from_audio(path: Path) -> str:
    try:
        if not GENAI_AVAILABLE or not settings.gemini_api_key or not genai:
            return "[Audio Transcription Failed: API Key missing or Library incompatible]"
            
        myfile = genai.upload_file(path)
        model = genai.GenerativeModel("gemini-1.5-flash")
        result = model.generate_content(["Generate a transcript of this audio:", myfile])
        return f"[Audio Transcript]\n{result.text}"
    except Exception as e:
        return f"[Audio processing failed: {e}]"

def extract_text_from_file(file_path: Path) -> str:
    """Main entry point to extract text based on extension."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    ext = path.suffix.lower()
    text = ""

    if ext == ".pdf":
        text = extract_text_from_pdf(path)
    elif ext == ".docx":
        text = extract_text_from_docx(path)
    elif ext in [".pptx", ".ppt"]:
        text = extract_text_from_pptx(path)
    elif ext == ".txt":
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    elif ext in [".jpg", ".jpeg", ".png"]:
        text = extract_text_from_image(path)
    elif ext in [".mp3", ".wav", ".m4a"]:
        text = extract_text_from_audio(path)
    else:
        # Try generic read for unknown text types
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except:
            raise ValueError(f"Unsupported file type: {ext}")

    if not text.strip():
        return f"[File: {path.name} processed but no text found]"
        
    return text
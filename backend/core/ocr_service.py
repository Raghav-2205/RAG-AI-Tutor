# backend/core/ocr_service.py

"""
Optional OCR for image-based PDFs using Tesseract.
Used by: file_handler.py (if images detected)
"""

try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    pytesseract = None


class OCRService:
    """OCR service for extracting text from images"""
    
    def __init__(self):
        self.available = OCR_AVAILABLE
    
    def extract_text_from_image(self, image_path: str) -> str:
        """Extract text from image using Tesseract OCR"""
        if not self.available:
            return "OCR not available - install pytesseract + Tesseract binary"
        
        try:
            img = Image.open(image_path)
            text = pytesseract.image_to_string(img)
            return text.strip()
        except Exception as e:
            return f"OCR failed: {str(e)}"
    
    def is_ocr_needed(self, file_path: str) -> bool:
        """Simple heuristic: OCR if file has many images/low text density"""
        # For now, just return False - enable later if needed
        return False


def extract_text_from_image(image_path: str) -> str:
    """Extract text from image using Tesseract OCR"""
    if not OCR_AVAILABLE:
        return "OCR not available - install pytesseract + Tesseract binary"
    
    try:
        img = Image.open(image_path)
        text = pytesseract.image_to_string(img)
        return text.strip()
    except Exception as e:
        return f"OCR failed: {str(e)}"


def is_ocr_needed(file_path: str) -> bool:
    """Simple heuristic: OCR if file has many images/low text density"""
    # For now, just return False - enable later if needed
    return False


# Global OCR service instance
ocr_service = OCRService()

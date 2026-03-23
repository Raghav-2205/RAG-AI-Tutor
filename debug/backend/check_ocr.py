import sys
try:
    import pytesseract
    from PIL import Image
    print(f"✅ Pytesseract module found: {pytesseract.__version__}")
    
    # Check if tesseract binary is path
    try:
        # This might fail if tesseract is not in PATH
        # We'll just print the tesseract_cmd
        print(f"Tesseract CMD: {pytesseract.pytesseract.tesseract_cmd}")
    except:
        pass

except ImportError:
    print("❌ Pytesseract NOT installed")

try:
    import pypdf
    print(f"✅ pypdf found: {pypdf.__version__}")
except ImportError:
    print("❌ pypdf NOT installed")

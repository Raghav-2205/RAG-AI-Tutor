#!/usr/bin/env python3
"""
Preprocess and clean study materials for RAG pipeline
Handles PDF extraction, text cleaning, chunking
"""

import re
import PyPDF2
from pathlib import Path
import nltk
from nltk.corpus import stopwords
from nltk.tokenize import sent_tokenize, word_tokenize

nltk.download('punkt', quiet=True)
nltk.download('stopwords', quiet=True)

def clean_text(text):
    """Clean and normalize text"""
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text)
    
    # Remove special characters but keep academic symbols
    text = re.sub(r'[^\w\s\-–—\.,;:!?()[\]{}"\'°±√∑∫πμστφχψωαβγδεζηθικλμνξοπρςστυφχψω]', ' ', text)
    
    # Remove page numbers and headers
    text = re.sub(r'\b\d{1,3}\b\s?', '', text)
    
    # Normalize quotes
    text = text.replace('``', '"').replace("''", '"')
    
    return text.strip()

def extract_pdf_text(pdf_path):
    """Extract text from PDF"""
    text = ""
    with open(pdf_path, 'rb') as file:
        reader = PyPDF2.PdfReader(file)
        for page in reader.pages:
            text += page.extract_text() + "\n"
    return clean_text(text)

def chunk_text(text, chunk_size=500, overlap=50):
    """Split text into overlapping chunks"""
    sentences = sent_tokenize(text)
    chunks = []
    
    for i in range(0, len(sentences), chunk_size//20):
        chunk = ' '.join(sentences[i:i + chunk_size//20])
        if len(chunk) > 100:  # Minimum chunk size
            chunks.append(chunk)
    
    return chunks

def preprocess_directory(input_dir="study_materials", output_dir="processed"):
    """Process entire directory"""
    Path(output_dir).mkdir(exist_ok=True)
    
    for pdf_file in Path(input_dir).glob("*.pdf"):
        print(f"Processing {pdf_file.name}...")
        
        text = extract_pdf_text(pdf_file)
        chunks = chunk_text(text)
        
        # Save processed chunks
        output_file = Path(output_dir) / f"{pdf_file.stem}_chunks.txt"
        with open(output_file, 'w') as f:
            for i, chunk in enumerate(chunks):
                f.write(f"CHUNK_{i}:\n{chunk}\n\n")
        
        print(f"✅ Created {len(chunks)} chunks")

if __name__ == "__main__":
    preprocess_directory()

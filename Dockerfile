FROM python:3.10-slim

# Prevent Python from writing pyc files and keep stdout unbuffered
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    tesseract-ocr \
    ffmpeg \
    libsm6 \
    libxext6 \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the requirements file and install python packages
COPY requirements.txt /app/
COPY backend/requirements.txt /app/backend/
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -r backend/requirements.txt

# Copy backend, frontend, and core application files
COPY backend /app/backend
COPY frontend /app/frontend
COPY data /app/data
COPY run.py /app/

RUN mkdir -p /app/uploads /app/chroma_data

# Expose port 8000
EXPOSE 8000

# Set Python path so `backend` module can be discovered
ENV PYTHONPATH=/app

# Run through the repo entrypoint so env-driven host/port settings stay consistent.
CMD ["python", "run.py"]

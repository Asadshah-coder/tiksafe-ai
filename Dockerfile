# TikSave AI — single image for both API and Streamlit frontend.
# FFmpeg is installed via apt so video processing works out of the box.
FROM python:3.11-slim

# Install FFmpeg (and ffprobe) for media processing
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1 \
    TIKSAFE_ENV=production \
    TIKSAFE_TEMP_DIR=/app/temp

EXPOSE 8000 8501

# Default: run the API. docker-compose overrides the command for the web service.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

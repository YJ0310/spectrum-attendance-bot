# Dockerfile for 24/7 SPeCTRUM Auto-Attendance Telegram Bot & Mini App
FROM python:3.11-slim

# Install system dependencies, Chromium, and Chrome Driver
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    curl \
    tzdata \
    fonts-liberation \
    libasound2 \
    libnss3 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Set timezone to Malaysia (Kuala Lumpur)
ENV TZ=Asia/Kuala_Lumpur
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Set environment variables for headless Chrome and cloud deployment
ENV HEADLESS_ONLY=1
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Expose HTTP port
EXPOSE 8000

# Container entrypoint: run unified FastAPI web service and background daemons
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}"]

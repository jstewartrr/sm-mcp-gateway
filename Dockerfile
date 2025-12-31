FROM python:3.11-slim-bookworm

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    libnss3 \
    libxss1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    libdrm2 \
    libgbm1 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libpango-1.0-0 \
    libcairo2 \
    libcups2 \
    libxshmfence1 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright and chromium browser
RUN playwright install chromium && playwright install-deps chromium

# Copy Flask-based proxy gateway (Claude.ai compatible)
COPY app.py .
COPY gateway.py .
COPY gateway_sse.py .
COPY scrapers/ ./scrapers/

# Expose port
EXPOSE 8080

# Run Flask proxy gateway (JSON-RPC compatible with Claude.ai)
ENV PORT=8080
CMD ["python", "app.py"]

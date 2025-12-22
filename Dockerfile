# Sovereign Mind MCP Gateway
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for Snowflake
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY gateway.py .
COPY gateway_sse.py .

# Expose port
EXPOSE 8000

# Environment defaults
ENV MCP_TRANSPORT=streamable_http
ENV PORT=8000

# Run the gateway (default: HTTP transport)
CMD ["python", "gateway.py"]

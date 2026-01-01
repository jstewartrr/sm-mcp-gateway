FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn boto3
COPY mcp_server.py .
EXPOSE 8080
CMD ["uvicorn", "mcp_server:app", "--host", "0.0.0.0", "--port", "8080"]

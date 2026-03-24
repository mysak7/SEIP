FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py dynamodb.py ./

ENV PYTHONUNBUFFERED=1
ENV MCP_TRANSPORT=http
ENV MCP_PORT=8765
ENV AWS_REGION=eu-central-1
ENV DYNAMODB_TABLE=dev-security-events
ENV PATTERNS_TABLE=dev-seip-patterns
ENV SERVICE_NAME=seip-mcp

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8765/health')" 2>/dev/null || exit 1

CMD ["python", "server.py", "--http", "8765"]

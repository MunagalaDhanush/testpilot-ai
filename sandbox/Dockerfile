FROM python:3.11-slim

WORKDIR /sandbox

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install common test frameworks
RUN pip install --no-cache-dir \
    pytest==8.3.4 \
    pytest-asyncio==0.25.0 \
    pytest-cov==6.0.0 \
    httpx==0.28.1 \
    pydantic==2.10.5 \
    anyio==4.7.0

# Mount point for test files at runtime
VOLUME ["/sandbox/tests"]

# Run pytest with JSON output for parsing
CMD ["pytest", "/sandbox/tests", "--tb=short", "--json-report", "--json-report-file=/sandbox/results.json", "-v"]

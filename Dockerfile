# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# MEMORY OPTIMIZATIONS FOR RENDER FREE TIER
# Prevents memory fragmentation in C/C++ libraries like curl_cffi
ENV MALLOC_ARENA_MAX=2 
ENV PYTHONUNBUFFERED=1

# Install build dependencies for curl-cffi
RUN apt-get update && apt-get install -y \
    ca-certificates \
    gcc \
    g++ \
    make \
    libffi-dev \
    libssl-dev \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for better caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Expose port for Render
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8080/health', timeout=5)"

# Run the application
CMD ["python", "standalone_monitor2.py"]

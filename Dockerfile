# Stage 1: Build Stage
FROM python:3.9-slim as builder

WORKDIR /app

# Install build dependencies if any (e.g., for selectolax or tgcrypto)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install requirements to a local folder
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Stage 2: Final Runtime Stage
FROM python:3.9-slim

# Install ONLY the necessary runtime system dependency
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the installed python packages from the builder stage
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy the application code
COPY . .

# Create the specific temp/log directories used by the bot [cite: 20]
RUN mkdir -p logs temp && \
    chmod +x main.py cleanup.py && \
    useradd -m -u 1000 animebot && \
    chown -R animebot:animebot /app

USER animebot

# Health check using the internal port defined in config [cite: 5, 18]
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

# Use the python binary directly to run the bot [cite: 20]
CMD ["python", "main.py"]
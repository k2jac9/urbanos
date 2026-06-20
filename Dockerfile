# ARM64-native image for the ASUS Ascent GX10 (NVIDIA GB10 / DGX OS).
# Build on the box, or cross-build with: docker build --platform linux/arm64 -t civic-analyst .
FROM --platform=linux/arm64 python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY scripts/ ./scripts/

EXPOSE 8000
CMD ["uvicorn", "urbanos.risk.api.server:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "src"]

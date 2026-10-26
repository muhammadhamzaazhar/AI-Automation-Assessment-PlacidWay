FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Run as a non-root user (uid 1000 is what Hugging Face Spaces expects).
RUN useradd --create-home --uid 1000 appuser
COPY --chown=appuser:appuser . .
USER appuser

EXPOSE 7860
# --proxy-headers: behind the host's proxy, use the real client IP for rate limiting.
CMD uvicorn app.api:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips="*"

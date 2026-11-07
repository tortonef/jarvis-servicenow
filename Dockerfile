FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# non-root user; /models is pre-created so the named volume inherits its ownership
RUN useradd --create-home jarvis && mkdir /models && chown jarvis /models
COPY jarvis jarvis
COPY seed seed
COPY db db
COPY procedures procedures
USER jarvis

ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 FASTEMBED_CACHE_PATH=/models JARVIS_HOST=0.0.0.0
CMD ["python", "-m", "jarvis.server"]
